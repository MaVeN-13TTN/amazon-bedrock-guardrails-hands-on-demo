"""FastAPI application for the Kilimo Desk guardrail demo.

Runs two ways from the same code:
  local   uvicorn app.main:app --reload
  Lambda  lambda_handler.handler  (Mangum adapter)
"""
import logging
from functools import lru_cache

from botocore.exceptions import BotoCoreError, ClientError
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app import scenario
from app.config import Settings, get_settings
from app.guardrails import GuardrailNotConfigured, GuardrailService
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
    to go fix model access; a generic 500 tells you nothing.
    """
    if isinstance(exc, GuardrailNotConfigured):
        return HTTPException(status_code=503, detail=str(exc))
    if isinstance(exc, ClientError):
        err = exc.response.get("Error", {})
        code = err.get("Code", "ClientError")
        detail = f"{code}: {err.get('Message', '')}".strip()
        status = 403 if code in ("AccessDeniedException", "UnrecognizedClientException") else 502
        log.error("bedrock call failed: %s", detail)
        return HTTPException(status_code=status, detail=detail)
    if isinstance(exc, BotoCoreError):
        log.error("boto error: %s", exc)
        return HTTPException(status_code=502, detail=f"{type(exc).__name__}: {exc}")
    log.exception("unhandled error")
    return HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}")


@app.get("/health", response_model=HealthResponse, tags=["meta"])
def health(cfg: Settings = Depends(get_settings)) -> HealthResponse:
    return HealthResponse(
        status="ok" if cfg.guardrail_active else "degraded",
        guardrail_active=cfg.guardrail_active,
        region=cfg.aws_region,
    )


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
        if screened.intervened:
            return _respond(stages, scenario.BLOCKED_INPUT_MESSAGE, "screen")

        # Forward the screened text: PII masked at stage 1 must not be handed
        # back to the model in the clear.
        answered = svc.answer(screened.text or text)
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
