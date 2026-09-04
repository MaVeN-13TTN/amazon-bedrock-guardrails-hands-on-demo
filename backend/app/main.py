"""FastAPI application for the Kilimo Desk guardrail demo.

Runs two ways from the same code:
  local   uvicorn app.main:app --reload
  Lambda  lambda_handler.handler  (Mangum adapter)
"""
import logging
import os
import re
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any

from botocore.exceptions import (
    BotoCoreError,
    ClientError,
    ConnectionError,
    ConnectTimeoutError,
    ParamValidationError,
    ReadTimeoutError,
)
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app import scenario
from app.config import Settings, get_settings
from app.guardrails import (
    GuardrailNotConfigured,
    GuardrailService,
    ReplayUnmatched,
    StageFailure,
)
from app.schemas import (
    AskRequest,
    AskResponse,
    ContextResponse,
    HealthResponse,
    StageResult,
    VerifyRequest,
)

settings = get_settings()
logging.basicConfig(
    level=settings.log_level,
    format='{"level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}',
)
log = logging.getLogger("kilimo")

app = FastAPI(
    title="Kilimo Desk API",
    description=(
        f"Member-support assistant for {scenario.ORG}, demonstrating Amazon "
        "Bedrock Guardrails as a screen / answer / verify pipeline."
    ),
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)


@lru_cache
def get_service() -> GuardrailService:
    return GuardrailService(get_settings())


def _fail(exc: Exception) -> HTTPException:
    """Turn AWS SDK errors into something readable on stage.

    A live demo needs the actual AWS message — 'AccessDeniedException' tells you
    to go fix model access; a generic 500 tells you nothing. The body is
    structured rather than prose so the Background_View can name the failing
    stage without parsing a sentence.
    """
    if isinstance(exc, GuardrailNotConfigured):
        return HTTPException(status_code=503, detail=str(exc))

    # Replay is active and this prompt was never recorded. Nothing is broken, so
    # this must not read like a failure: name the covered prompts so a presenter
    # can pick one that works.
    if isinstance(exc, ReplayUnmatched):
        return HTTPException(
            status_code=409,
            detail={
                "kind": "replay_unmatched",
                "stage": None,
                "detail": (
                    "Replay_Mode is active and no recorded result exists for this "
                    "prompt. Choose one of the recorded prompts, or unset "
                    "REPLAY_MODE to call AWS live."
                ),
                "case_ids": exc.case_ids,
                "prompts": exc.prompts,
            },
        )

    stage = exc.stage if isinstance(exc, StageFailure) else None
    elapsed = exc.elapsed_ms if isinstance(exc, StageFailure) else None
    cause = exc.cause if isinstance(exc, StageFailure) else exc

    def body(kind: str, detail: str, **extra) -> dict:
        return {"kind": kind, "stage": stage, "detail": detail, **extra}

    # A rejected parameter is not a guardrail intervention and must not read like
    # one: the field is unsupported by this SDK, and the pipeline stopped.
    if isinstance(cause, ParamValidationError):
        detail = f"{stage or 'pipeline'} stage supplied a parameter this SDK rejects: {cause}"
        log.error("parameter validation failed: %s", detail)
        return HTTPException(
            status_code=400,
            detail=body("parameter_validation", detail, parameter=_rejected_parameter(cause)),
        )

    # A timeout is reported by elapsed time, with no AWS error code asserted —
    # there is no code, because no response arrived.
    if isinstance(cause, ReadTimeoutError | ConnectTimeoutError | ConnectionError):
        detail = f"{stage or 'pipeline'} stage timed out after {elapsed}ms"
        log.error("bedrock timed out: %s", detail)
        return HTTPException(
            status_code=504, detail=body("timeout", detail, elapsed_ms=elapsed)
        )

    if isinstance(cause, ClientError):
        err = cause.response.get("Error", {})
        code = err.get("Code", "ClientError")
        detail = f"{code}: {err.get('Message', '')}".strip()
        status = 403 if code in ("AccessDeniedException", "UnrecognizedClientException") else 502
        log.error("bedrock call failed: %s", detail)
        return HTTPException(
            status_code=status, detail=body("aws_error", detail, aws_error_code=code)
        )

    if isinstance(cause, BotoCoreError):
        log.error("boto error: %s", cause)
        return HTTPException(
            status_code=502, detail=body("boto_error", f"{type(cause).__name__}: {cause}")
        )

    log.exception("unhandled error")
    return HTTPException(
        status_code=500, detail=body("error", f"{type(cause).__name__}: {cause}")
    )


def _rejected_parameter(exc: ParamValidationError) -> str | None:
    """Pull the offending parameter name out of botocore's report, if it names one."""
    match = re.search(r'Unknown parameter[^:]*: "?(\w+)"?', str(exc))
    return match.group(1) if match else None


@app.get("/health", response_model=HealthResponse, tags=["meta"])
def health(cfg: Settings = Depends(get_settings)) -> HealthResponse:
    return HealthResponse(
        status="ok" if cfg.guardrail_active else "degraded",
        guardrail_active=cfg.guardrail_active,
        region=cfg.aws_region,
    )


@app.get("/api/diagnostics/sdk", tags=["meta"])
def diagnostics_sdk(
    cfg: Settings = Depends(get_settings),
    svc: GuardrailService = Depends(get_service),
) -> dict:
    """Which SDK is in force here, and does it accept the fields the pipeline sends?

    This exists because the answer differs between environments and neither
    difference is obvious. Locally the pinned boto3 governs; in Lambda the runtime
    supplies its own, because `scripts/package-backend.sh` strips boto3 and
    botocore from the bundle. A field the pin accepts may be absent from the
    runtime's service model, or the reverse.

    Both failure directions are probed, because they fail differently:
      - a **request** field the SDK does not know raises ParamValidationError
        before the call leaves the machine — loud (validation log V-14)
      - a **response** field the SDK does not know is dropped silently, and reads
        as absent — indistinguishable from AWS not sending it (V-24)

    Read-only: it calls ApplyGuardrail, which invokes no model, and creates
    nothing.
    """
    import platform

    import boto3
    import botocore

    report: dict[str, Any] = {
        "boto3": boto3.__version__,
        "botocore": botocore.__version__,
        "python": platform.python_version(),
        "architecture": platform.machine(),
        "region": cfg.aws_region,
        "utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        # AWS_LAMBDA_FUNCTION_NAME is the reliable signal. AWS_EXECUTION_ENV is
        # not: other tools set it too — this repository's own diagnostics reported
        # "AmazonQ-For-CLI" from a local shell — so it is recorded verbatim for
        # reference but never used to decide where the code is running.
        "execution_env": os.environ.get("AWS_EXECUTION_ENV"),
        "lambda_runtime": (
            os.environ.get("AWS_EXECUTION_ENV")
            if os.environ.get("AWS_LAMBDA_FUNCTION_NAME")
            else None
        ),
        "lambda_function": os.environ.get("AWS_LAMBDA_FUNCTION_NAME"),
        "environment": "lambda" if os.environ.get("AWS_LAMBDA_FUNCTION_NAME") else "local",
        "boto3_stripped_from_bundle": True,
        "pinned_locally": "1.38.0",
    }

    # Does the service model declare the fields we depend on? Cheaper and more
    # precise than inferring from a version string.
    try:
        session = botocore.session.get_session()
        runtime = session.get_service_model("bedrock-runtime")
        report["outputScope_in_service_model"] = (
            "outputScope"
            in runtime.operation_model("ApplyGuardrail").input_shape.members
        )
        topic = session.get_service_model("bedrock").operation_model(
            "GetGuardrail"
        ).output_shape.members.get("topicPolicy")
        report["tier_in_service_model"] = topic is not None and "tier" in topic.members
    except Exception as exc:  # noqa: BLE001 — diagnostics must not fail the request
        report["service_model_error"] = f"{type(exc).__name__}: {exc}"

    # Then actually send it, at both call sites that pass it. A service model can
    # declare a field the API still rejects.
    report["probes"] = {}
    for site, call in (
        ("screen", lambda: svc.screen("When are the collection points open?")),
        ("verify", lambda: svc.verify(
            "When are the collection points open?",
            "The collection points open 06:00 to 10:00 on Tuesdays and Fridays.",
        )),
    ):
        probe: dict[str, Any] = {"outputScope": "FULL"}
        try:
            result = call()
            probe["accepted"] = True
            probe["rejection"] = None
            # outputScope=FULL's whole purpose: assessments that evaluated the text
            # and allowed it. A count of zero means the parameter was accepted and
            # ignored, which is a different failure from rejection.
            probe["assessments_with_action_none"] = sum(
                1 for h in result.hits if h.action in (None, "NONE")
            )
            probe["model_invoked"] = result.model_invoked
            probe["latency_ms"] = result.latency_ms
        except Exception as exc:  # noqa: BLE001 — the rejection is the measurement
            cause = exc.cause if isinstance(exc, StageFailure) else exc
            probe["accepted"] = not isinstance(cause, ParamValidationError)
            probe["rejection"] = str(cause)[:500]
            probe["rejected_parameter"] = (
                _rejected_parameter(cause) if isinstance(cause, ParamValidationError) else None
            )
        report["probes"][site] = probe

    return report


@app.get("/api/context", response_model=ContextResponse, tags=["meta"])
def context(cfg: Settings = Depends(get_settings)) -> ContextResponse:
    """Everything the frontend needs to render itself, including the bulletin."""
    return ContextResponse(
        org=scenario.ORG,
        assistant=scenario.ASSISTANT,
        county=scenario.COUNTY,
        region=cfg.aws_region,
        model=cfg.bedrock_model_id,
        guardrail_id=cfg.guardrail_id or None,
        guardrail_version=cfg.guardrail_version if cfg.guardrail_active else None,
        guardrail_active=cfg.guardrail_active,
        bulletin=scenario.EXTENSION_BULLETIN,
        denied_topics=[t["name"] for t in scenario.DENIED_TOPICS],
        blocked_words=list(scenario.BLOCKED_WORDS),
        grounding_threshold=scenario.GROUNDING_THRESHOLD,
        relevance_threshold=scenario.RELEVANCE_THRESHOLD,
        bulletin_facts=scenario.BULLETIN_FACTS,
        about_sections=scenario.ABOUT_SECTIONS,
    )


@app.post("/api/ask", response_model=AskResponse, tags=["pipeline"])
def ask(
    body: AskRequest,
    cfg: Settings = Depends(get_settings),
    svc: GuardrailService = Depends(get_service),
) -> AskResponse:
    """Run the pipeline: screen -> answer -> verify.

    A request rejected at screen() never reaches the model. That is the saving,
    and the response says so via each stage's `model_invoked` flag.
    """
    text = body.input.strip()
    if len(text) > cfg.max_input_chars:
        raise HTTPException(
            status_code=413,
            detail=f"input longer than {cfg.max_input_chars} characters",
        )

    stages: list[StageResult] = []
    try:
        screened = svc.screen(text)
        stages.append(screened)
        # Masking is an intervention too: AWS returns GUARDRAIL_INTERVENED with
        # actionReason "Guardrail masked." and the rewritten text in outputs. Only a
        # genuine block should halt the request — a masked request continues with the
        # personal data removed, which is the whole point of ANONYMIZE.
        # See docs/validation-log.md V-15.
        #
        # Judge only the findings that *did* something. With outputScope=FULL — which
        # this demo enables precisely so the UI can show which policies looked and
        # allowed — most findings carry the action "NONE". That is a string, and a
        # non-empty string is truthy, so filtering on `if hit.action` keeps them and
        # every "NONE" then fails an `== "ANONYMIZED"` test. The effect was that any
        # masked request accompanied by a NONE finding was refused as though it had
        # been blocked: exactly the V-15 defect, returning by a different door.
        # See docs/validation-log.md V-31.
        acted = [hit for hit in screened.hits if hit.action and hit.action != "NONE"]
        masked_only = screened.intervened and bool(acted) and all(
            hit.action == "ANONYMIZED" for hit in acted
        )
        if screened.intervened and not masked_only:
            return _respond(stages, scenario.BLOCKED_INPUT_MESSAGE, "screen")

        # Forward the screened text: PII masked at stage 1 must not be handed
        # back to the model in the clear.
        # The masked text goes to the model; the original picks a fallback answer.
        answered = svc.answer(screened.text or text, original_text=text)
        stages.append(answered)
        if answered.intervened:
            return _respond(stages, answered.text or scenario.BLOCKED_OUTPUT_MESSAGE, "answer")

        verified = svc.verify(text, answered.text or "")
        stages.append(verified)
        return _respond(
            stages,
            scenario.BLOCKED_OUTPUT_MESSAGE if verified.intervened else (answered.text or ""),
            "verify" if verified.intervened else None,
        )
    except Exception as exc:  # noqa: BLE001 — mapped to a readable HTTP error
        raise _fail(exc) from exc


@app.post("/api/verify", response_model=StageResult, tags=["pipeline"])
def verify(
    body: VerifyRequest,
    svc: GuardrailService = Depends(get_service),
) -> StageResult:
    """Judge a supplied answer against the bulletin. Drives the grounding lane."""
    try:
        return svc.verify(body.question.strip(), body.answer.strip(), body.reference)
    except Exception as exc:  # noqa: BLE001
        raise _fail(exc) from exc


def _respond(stages, final, stopped_at) -> AskResponse:
    return AskResponse(
        stages=stages,
        final=final,
        stopped_at=stopped_at,
        total_latency_ms=sum(s.latency_ms or 0 for s in stages),
    )
