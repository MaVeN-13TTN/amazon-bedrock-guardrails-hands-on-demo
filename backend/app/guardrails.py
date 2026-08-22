"""Bedrock Guardrails as a three-stage pipeline: screen -> answer -> verify.

  screen()  ApplyGuardrail on the user's text.   No foundation model involved.
  answer()  Converse with the guardrail attached. The only model call.
  verify()  ApplyGuardrail on the answer, with the reference document supplied,
            checking the answer is grounded in it and relevant to the question.

Stages 1 and 3 use `apply_guardrail`, which requires no model. That is what makes
a guardrail portable: the same policy can front a Bedrock model, a self-hosted
model, or a third-party API, because evaluation is independent of inference.
"""
import contextlib
import functools
import json
import logging
import pathlib
import time
from collections.abc import Callable
from typing import Any, NamedTuple

import boto3
from botocore.config import Config

from app import scenario
from app.config import Settings
from app.replay import ReplayCase, ReplayStore
from app.schemas import PolicyHit, ReplayMeta, Stage, StageResult

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


# --- answer-stage fallback ---------------------------------------------------
# When bedrock:InvokeModel is denied — an organisation SCP, no model access, or a
# throttle — the answer stage cannot run. Stages 1 and 3 still can, because
# ApplyGuardrail needs no model. Rather than lose the whole pipeline, the answer
# stage substitutes a canned answer drawn from the bulletin and labels itself as
# a fallback. The guardrail work either side of it remains entirely live.
#
# This is the shape of Requirement 7's Replay_Mode, narrowed to the one stage
# that needs a model. See docs/validation-log.md V-12.

_FALLBACK_PATH = pathlib.Path(__file__).resolve().parent / "fixtures" / "answer_fallback.json"


@functools.lru_cache(maxsize=1)
def _fallback_answers() -> dict:
    if _FALLBACK_PATH.is_file():
        return json.loads(_FALLBACK_PATH.read_text(encoding="utf-8"))
    return {"answers": [], "default": "", "captured_utc": "", "region": "", "tier": "",
            "guardrail_version": ""}


def canned_answer(user_text: str) -> str:
    """Pick the bulletin-grounded answer whose keywords the question matches."""
    data = _fallback_answers()
    lowered = user_text.lower()
    for entry in data.get("answers", []):
        if any(keyword in lowered for keyword in entry["match"]):
            return entry["text"]
    return data.get("default", "")


def _is_model_unavailable(exc: Exception) -> bool:
    """Is this a failure of model access specifically, rather than a bug?

    Deliberately narrow. A guardrail failure, a parameter rejection or a coding
    error must still surface — only an authorisation or throttling failure on the
    model itself is worth falling back for.
    """
    cause = exc.cause if isinstance(exc, StageFailure) else exc
    code = getattr(cause, "response", {}).get("Error", {}).get("Code", "")
    return code in {
        "AccessDeniedException",
        "ThrottlingException",
        "ServiceUnavailableException",
        "ModelNotReadyException",
        "ValidationException",
    }


class StageFailure(RuntimeError):
    """An AWS call failed, tagged with the pipeline stage that made it.

    Without this, a failure mid-pipeline tells you a Bedrock call broke but not
    which of the three made it — and the Background_View has to name the stage.
    """

    def __init__(self, stage: str, cause: Exception, elapsed_ms: int | None = None):
        super().__init__(f"{stage} stage: {type(cause).__name__}: {cause}")
        self.stage = stage
        self.cause = cause
        self.elapsed_ms = elapsed_ms


@contextlib.contextmanager
def _stage(name: str):
    """Tag any exception raised inside with the stage that raised it."""
    started = time.perf_counter()
    try:
        yield
    except (GuardrailNotConfigured, StageFailure):
        raise
    except Exception as exc:
        raise StageFailure(name, exc, _ms(started)) from exc


def _meta(case: ReplayCase) -> ReplayMeta:
    """Capture provenance for a replayed stage, so nothing claims to be live."""
    return ReplayMeta(
        captured_utc=case.captured_utc,
        region=case.region,
        tier=case.tier,
        guardrail_version=case.guardrail_version,
    )


class ReplayUnmatched(RuntimeError):
    """Replay is active but no fixture matches this prompt.

    Distinct from a failure: nothing is broken, the prompt simply was not
    recorded. `main.py` surfaces it as a 409 naming the covered prompts so a
    presenter can pick one that works.
    """

    def __init__(self, prompt: str, case_ids: list[str], prompts: list[str]):
        super().__init__(f"no recorded result for this prompt ({len(prompts)} cases available)")
        self.prompt = prompt
        self.case_ids = case_ids
        self.prompts = prompts


class GuardrailService:
    def __init__(self, settings: Settings, client=None, replay: ReplayStore | None = None):
        self.settings = settings
        if replay is not None:
            self._replay: ReplayStore | None = replay
            self._client = client
        elif settings.replay_mode:
            # Nothing to construct and nothing to authenticate. This is the whole
            # point of Replay_Mode: no credential chain is consulted, so the
            # pipeline runs with AWS entirely absent.
            self._replay = ReplayStore(settings.replay_path, settings.guardrail_tier)
            self._client = None
            log.info(
                "Replay_Mode active: %d recorded cases from %s (tier %s); "
                "no Bedrock client constructed",
                len(self._replay), settings.replay_path, settings.guardrail_tier,
            )
        else:
            self._replay = None
            self._client = client or boto3.client(
                "bedrock-runtime", region_name=settings.aws_region, config=_BOTO_CONFIG
            )

    # --- helpers -----------------------------------------------------------

    @property
    def replaying(self) -> bool:
        return self._replay is not None

    def _replayed_stage(self, prompt: str, stage: Stage) -> StageResult:
        """Return the recorded result for one stage of a matched case.

        A case that stopped before this stage has no record of it — a dosing
        prompt blocked at screen never reached the model — so the caller is told
        the stage did not run rather than being handed a fabricated result.
        """
        assert self._replay is not None
        case = self._replay.lookup(prompt)
        if case is None:
            raise ReplayUnmatched(prompt, self._replay.case_ids, self._replay.prompts)
        for recorded in case.stages:
            if recorded.stage == stage:
                return recorded.model_copy(update={"replayed": _meta(case)})
        raise ReplayUnmatched(prompt, self._replay.case_ids, self._replay.prompts)

    def _require_guardrail(self) -> None:
        # Under replay there is no guardrail to require: no identifier is used and
        # no call is made.
        if self.replaying:
            return
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
        if self.replaying:
            return self._replayed_stage(user_text, "screen")
        started = time.perf_counter()
        with _stage("screen"):
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

    def answer(self, user_text: str, with_guardrail: bool = True,
               original_text: str | None = None) -> StageResult:
        """Call the model. With `with_guardrail`, the guardrail rides along.

        `original_text` is the question as the member asked it, used only to pick a
        fallback answer when the model is unreachable — `user_text` may have been
        rewritten by masking at stage 1, which makes for poor keyword matching.
        """
        if self.replaying:
            return self._replayed_stage(original_text or user_text, "answer")
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

        with _stage("answer"):
            try:
                resp = self._client.converse(**kwargs)
            except Exception as exc:  # noqa: BLE001
                if not self.settings.answer_fallback or not _is_model_unavailable(exc):
                    raise
                # The model is unreachable. Substitute a bulletin-grounded answer so
                # stages 1 and 3 — the guardrail work — still run live.
                data = _fallback_answers()
                log.warning("answer stage falling back to a canned response: %s", exc)
                return StageResult(
                    stage="answer",
                    intervened=False,
                    stop_reason="fallback_no_model",
                    text=canned_answer(original_text or user_text),
                    hits=[],
                    model_invoked=False,
                    latency_ms=_ms(started),
                    replayed=ReplayMeta(
                        captured_utc=data.get("captured_utc", ""),
                        region=data.get("region", ""),
                        tier=data.get("tier", ""),
                        guardrail_version=data.get("guardrail_version", ""),
                    ),
                    raw={
                        "info": "model unavailable; canned answer substituted",
                        "reason": str(exc)[:400],
                    },
                )
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
        if self.replaying:
            assert self._replay is not None
            # The Grounding_Tool supplies its own answer, so match on that first;
            # only fall back to the question for a member request replaying stage 3.
            found = self._replay.verify_case(question, model_answer)
            if found is not None:
                case, recorded = found
                return recorded.model_copy(update={"replayed": _meta(case)})
            return self._replayed_stage(question, "verify")
        started = time.perf_counter()
        reference = reference or scenario.EXTENSION_BULLETIN
        with _stage("verify"):
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
# The two Bedrock APIs report differently and both shapes have to be handled:
#   apply_guardrail -> a flat `assessments` list
#   converse        -> a `trace` where inputAssessment maps id -> assessment
#                      but outputAssessments maps id -> [assessment]


class _Section(NamedTuple):
    """One parsed section of an assessment, and how to turn its items into hits."""

    policy: str  # top-level assessment key
    items: str  # the list-valued key inside it
    build: Callable[[dict, str], PolicyHit]


def _content_filter(f: dict, where: str) -> PolicyHit:
    return PolicyHit(policy="content filter", detail=f.get("type"),
                     action=f.get("action"), where=where, score=f.get("confidence"))


def _denied_topic(t: dict, where: str) -> PolicyHit:
    return PolicyHit(policy="denied topic", detail=t.get("name"),
                     action=t.get("action"), where=where)


def _custom_word(w: dict, where: str) -> PolicyHit:
    return PolicyHit(policy="word filter", detail=w.get("match"),
                     action=w.get("action"), where=where)


def _managed_word(w: dict, where: str) -> PolicyHit:
    return PolicyHit(policy="managed word list", detail=w.get("type"),
                     action=w.get("action"), where=where)


def _pii_entity(p: dict, where: str) -> PolicyHit:
    return PolicyHit(policy="PII", detail=p.get("type"),
                     action=p.get("action"), where=where)


def _pii_regex(r: dict, where: str) -> PolicyHit:
    return PolicyHit(policy="PII regex", detail=r.get("name"),
                     action=r.get("action"), where=where)


def _grounding(g: dict, where: str) -> PolicyHit:
    """Grounding reports a score against a threshold, not a category match.

    Emitted whatever the action, because a check that ran and passed is the
    interesting half of the lesson — the score is the teaching material.
    """
    return PolicyHit(
        policy="grounding" if g.get("type") == "GROUNDING" else "relevance",
        detail=f"score {g.get('score')} vs threshold {g.get('threshold')}",
        action=g.get("action"), where=where,
        score=g.get("score"), threshold=g.get("threshold"),
        passed=g.get("action") == "NONE",
    )


# Fixed emission order. Hits come out in this sequence whatever order the keys
# arrive in, so the UI panels are stable and diffable against the raw payload.
_SECTIONS: tuple[_Section, ...] = (
    _Section("contentPolicy", "filters", _content_filter),
    _Section("topicPolicy", "topics", _denied_topic),
    _Section("wordPolicy", "customWords", _custom_word),
    _Section("wordPolicy", "managedWordLists", _managed_word),
    _Section("sensitiveInformationPolicy", "piiEntities", _pii_entity),
    _Section("sensitiveInformationPolicy", "regexes", _pii_regex),
    _Section("contextualGroundingPolicy", "filters", _grounding),
)

# Sections where action=NONE means "considered the text and passed", which is not
# a finding. Everywhere else a NONE action is still reported: a word or PII rule
# that matched is worth showing whatever was done about it, and a grounding score
# is the point of the check.
_DROP_NONE_ACTION = frozenset({"contentPolicy", "topicPolicy"})


def _walk(assessment: dict, where: str) -> list[PolicyHit]:
    """Parse one assessment into hits, in declared section order."""
    hits: list[PolicyHit] = []
    for section in _SECTIONS:
        block = assessment.get(section.policy) or {}
        for item in block.get(section.items) or []:
            if section.policy in _DROP_NONE_ACTION and item.get("action") == "NONE":
                continue
            hits.append(section.build(item, where))
    return hits


def parse_assessments(assessments: list | None, where: str) -> list[PolicyHit]:
    hits: list[PolicyHit] = []
    for a in assessments or []:
        hits.extend(_walk(a, where))
    return hits


def parse_trace(trace: dict | None) -> list[PolicyHit]:
    if not trace or "guardrail" not in trace:
        return []
    hits: list[PolicyHit] = []
    for phase, where in (("inputAssessment", "input"), ("outputAssessments", "output")):
        for _gid, block in (trace["guardrail"].get(phase) or {}).items():
            for a in block if isinstance(block, list) else [block]:
                hits.extend(_walk(a, where))
    return hits


def _ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def _strip(obj):
    """Drop boto3's ResponseMetadata so the raw panel shows only the assessment.

    Every other top-level key is preserved unchanged: the Background_View renders
    this verbatim, and a reader has to be able to match it against the findings.
    """
    if isinstance(obj, dict):
        return {k: v for k, v in obj.items() if k != "ResponseMetadata"}
    return obj
