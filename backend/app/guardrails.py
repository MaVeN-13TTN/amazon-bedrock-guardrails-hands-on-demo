"""Bedrock Guardrails as a three-stage pipeline: screen -> answer -> verify.

  screen()  ApplyGuardrail on the user's text.   No foundation model involved.
  answer()  Converse with the guardrail attached. The only model call.
  verify()  ApplyGuardrail on the answer, with the reference document supplied,
            checking the answer is grounded in it and relevant to the question.

Stages 1 and 3 use `apply_guardrail`, which requires no model. That is what makes
a guardrail portable: the same policy can front a Bedrock model, a self-hosted
model, or a third-party API, because evaluation is independent of inference.
"""
import logging
import time
from typing import Any

import boto3
from botocore.config import Config

from app import scenario
from app.config import Settings
from app.schemas import PolicyHit, StageResult

log = logging.getLogger(__name__)

# Retries and timeouts matter here: this runs inside a Lambda with a fixed budget,
# and three sequential Bedrock calls can otherwise outlast it silently.
_BOTO_CONFIG = Config(
    retries={"max_attempts": 3, "mode": "adaptive"},
    connect_timeout=5,
    read_timeout=25,
)


class GuardrailNotConfigured(RuntimeError):
    """Raised when a stage needing a guardrail is called without one."""


class GuardrailService:
    def __init__(self, settings: Settings, client=None):
        self.settings = settings
        self._client = client or boto3.client(
            "bedrock-runtime", region_name=settings.aws_region, config=_BOTO_CONFIG
        )

    # --- helpers -----------------------------------------------------------

    def _require_guardrail(self) -> None:
        if not self.settings.guardrail_active:
            raise GuardrailNotConfigured(
                "No guardrail configured. Set GUARDRAIL_ID (terraform output "
                "guardrail_id) and GUARDRAIL_ENABLED=true."
            )

    @property
    def _ids(self) -> dict[str, str]:
        return {
            "guardrailIdentifier": self.settings.guardrail_id,
            "guardrailVersion": self.settings.guardrail_version,
        }

    # --- stage 1: screen ---------------------------------------------------

    def screen(self, user_text: str) -> StageResult:
        """Evaluate user input against the policy. No model is invoked.

        outputScope=FULL returns every assessment, not only the ones that
        intervened, so the UI can show policies that considered the text and
        let it through.
        """
        self._require_guardrail()
        started = time.perf_counter()
        resp = self._client.apply_guardrail(
            **self._ids,
            source="INPUT",
            content=[{"text": {"text": user_text, "qualifiers": ["guard_content"]}}],
            outputScope="FULL",
        )
        return StageResult(
            stage="screen",
            intervened=resp.get("action") == "GUARDRAIL_INTERVENED",
            reason=resp.get("actionReason"),
            text="".join(o.get("text", "") for o in resp.get("outputs", [])) or user_text,
            hits=parse_assessments(resp.get("assessments"), "input"),
            model_invoked=False,
            latency_ms=_ms(started),
            raw=_strip(resp),
        )

    # --- stage 2: answer ---------------------------------------------------

    def answer(self, user_text: str, with_guardrail: bool = True) -> StageResult:
        """Call the model. With `with_guardrail`, the guardrail rides along."""
        started = time.perf_counter()
        kwargs: dict[str, Any] = {
            "modelId": self.settings.bedrock_model_id,
            "system": [{"text": scenario.SYSTEM_PROMPT}],
            "inferenceConfig": {"maxTokens": 400, "temperature": 0.2},
        }

        attach = with_guardrail and self.settings.guardrail_active
        if attach:
            # guardContent marks the span the guardrail evaluates. The system
            # prompt sits outside it, so our own boundary rules never trip our
            # own filters.
            kwargs["messages"] = [
                {"role": "user", "content": [{"guardContent": {"text": {"text": user_text}}}]}
            ]
            kwargs["guardrailConfig"] = {**self._ids, "trace": "enabled"}
        else:
            kwargs["messages"] = [{"role": "user", "content": [{"text": user_text}]}]

        resp = self._client.converse(**kwargs)
        text = "".join(
            b.get("text", "")
            for b in resp.get("output", {}).get("message", {}).get("content", [])
        )
        trace = resp.get("trace")
        return StageResult(
            stage="answer",
            # A guardrail block is not an exception: converse() returns normally
            # with this stopReason and the configured blocked message as text.
            intervened=resp.get("stopReason") == "guardrail_intervened",
            stop_reason=resp.get("stopReason"),
            text=text,
            hits=parse_trace(trace),
            model_invoked=True,
            latency_ms=_ms(started),
            raw=_strip(trace) if trace else {"info": "no guardrail attached to this call"},
        )

    # --- stage 3: verify ---------------------------------------------------

    def verify(self, question: str, model_answer: str, reference: str | None = None) -> StageResult:
        """Check the answer against a reference document.

        Three content blocks, each tagged with the qualifier that assigns its
        role. Block order does not matter; the qualifier does.
        """
        self._require_guardrail()
        started = time.perf_counter()
        reference = reference or scenario.EXTENSION_BULLETIN
        resp = self._client.apply_guardrail(
            **self._ids,
            source="OUTPUT",
            content=[
                {"text": {"text": reference, "qualifiers": ["grounding_source"]}},
                {"text": {"text": question, "qualifiers": ["query"]}},
                {"text": {"text": model_answer, "qualifiers": ["guard_content"]}},
            ],
            outputScope="FULL",
        )
        return StageResult(
            stage="verify",
            intervened=resp.get("action") == "GUARDRAIL_INTERVENED",
            reason=resp.get("actionReason"),
            hits=parse_assessments(resp.get("assessments"), "output"),
            model_invoked=False,
            latency_ms=_ms(started),
            raw=_strip(resp),
        )


# --- assessment parsing ----------------------------------------------------
# The two APIs report differently and both shapes have to be handled:
#   apply_guardrail -> a flat `assessments` list
#   converse        -> a `trace` where inputAssessment maps id -> assessment
#                      but outputAssessments maps id -> [assessment]

def _walk(assessment: dict, where: str, hits: list[PolicyHit]) -> None:
    for f in (assessment.get("contentPolicy") or {}).get("filters", []):
        if f.get("action") != "NONE":
            hits.append(PolicyHit(policy="content filter", detail=f.get("type"),
                                  action=f.get("action"), where=where,
                                  score=f.get("confidence")))
    for t in (assessment.get("topicPolicy") or {}).get("topics", []):
        if t.get("action") != "NONE":
            hits.append(PolicyHit(policy="denied topic", detail=t.get("name"),
                                  action=t.get("action"), where=where))
    wp = assessment.get("wordPolicy") or {}
    for w in wp.get("customWords", []):
        hits.append(PolicyHit(policy="word filter", detail=w.get("match"),
                              action=w.get("action"), where=where))
    for w in wp.get("managedWordLists", []):
        hits.append(PolicyHit(policy="managed word list", detail=w.get("type"),
                              action=w.get("action"), where=where))
    sip = assessment.get("sensitiveInformationPolicy") or {}
    for p in sip.get("piiEntities", []):
        hits.append(PolicyHit(policy="PII", detail=p.get("type"),
                              action=p.get("action"), where=where))
    for r in sip.get("regexes", []):
        hits.append(PolicyHit(policy="PII regex", detail=r.get("name"),
                              action=r.get("action"), where=where))
    # Grounding reports a score against a threshold, not a category match.
    for g in (assessment.get("contextualGroundingPolicy") or {}).get("filters", []):
        hits.append(PolicyHit(
            policy="grounding" if g.get("type") == "GROUNDING" else "relevance",
            detail=f"score {g.get('score')} vs threshold {g.get('threshold')}",
            action=g.get("action"), where=where,
            score=g.get("score"), threshold=g.get("threshold"),
            passed=g.get("action") == "NONE",
        ))


def parse_assessments(assessments: list | None, where: str) -> list[PolicyHit]:
    hits: list[PolicyHit] = []
    for a in assessments or []:
        _walk(a, where, hits)
    return hits


def parse_trace(trace: dict | None) -> list[PolicyHit]:
    if not trace or "guardrail" not in trace:
        return []
    hits: list[PolicyHit] = []
    for phase, where in (("inputAssessment", "input"), ("outputAssessments", "output")):
        for _gid, block in (trace["guardrail"].get(phase) or {}).items():
            for a in block if isinstance(block, list) else [block]:
                _walk(a, where, hits)
    return hits


def _ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def _strip(obj):
    """Drop boto3's ResponseMetadata so the raw panel shows only the assessment."""
    if isinstance(obj, dict):
        return {k: v for k, v in obj.items() if k != "ResponseMetadata"}
    return obj
