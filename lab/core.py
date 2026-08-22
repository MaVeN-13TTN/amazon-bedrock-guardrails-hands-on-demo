"""Preflight checks and the shared evaluation core.

Every subcommand runs `preflight()` before any AWS call. The distinction it draws
— missing prerequisite versus failed evaluation — is what lets the
Checkpoint_Verifier report a checkpoint as *not evaluated* rather than as a false
*unmet*, which would otherwise send an attendee hunting a defect that is really an
absent environment variable.
"""
from __future__ import annotations

import os
import pathlib
import sys
import time
from dataclasses import dataclass, field
from typing import Any

# The lab sits beside the backend and reuses its service and parser.
_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(_ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(_ROOT / "backend"))

from app.config import Settings  # noqa: E402
from app.guardrails import GuardrailService, StageFailure  # noqa: E402
from app.schemas import PolicyHit, StageResult  # noqa: E402

SCENARIO_PATH = _ROOT / "shared" / "scenario.json"
MAX_PROMPT_CHARS = 2000


class PreflightError(RuntimeError):
    """A prerequisite is absent. Names the variable and the command that sets it."""


class PromptError(ValueError):
    """A prompt violates a declared limit, detected before any AWS call."""


@dataclass
class Preflight:
    """What the environment supplies, resolved once per invocation."""

    guardrail_id: str
    region: str
    guardrail_version: str = "DRAFT"
    # Read from the guardrail, not assumed. "UNKNOWN" when GetGuardrail is not
    # permitted, so a record is never stamped with a tier nobody confirmed.
    tier: str = "UNKNOWN"
    account_id: str | None = None

    @property
    def settings(self) -> Settings:
        return Settings(
            guardrail_id=self.guardrail_id,
            guardrail_version=self.guardrail_version,
            guardrail_enabled=True,
            aws_region=self.region,
        )


def preflight(
    *,
    require_guardrail: bool = True,
    require_credentials: bool = True,
    client_factory=None,
) -> Preflight:
    """Resolve the environment, raising PreflightError naming what is absent.

    Runs before any Bedrock call so a missing variable costs nothing and reports
    a fix rather than an AWS error a reader has to interpret.
    """
    guardrail_id = os.environ.get("GUARDRAIL_ID", "").strip()
    if require_guardrail and not guardrail_id:
        raise PreflightError(
            "GUARDRAIL_ID is not set. Populate it with:\n"
            "  export GUARDRAIL_ID=$(terraform -chdir=infrastructure output -raw guardrail_id)"
        )

    region = (
        os.environ.get("AWS_REGION")
        or os.environ.get("AWS_DEFAULT_REGION")
        or ""
    ).strip()
    if not region:
        raise PreflightError(
            "No AWS Region resolved. Set it with:\n  export AWS_REGION=eu-west-1"
        )

    account_id = None
    if require_credentials:
        account_id = _check_credentials(region, client_factory)

    version = os.environ.get("GUARDRAIL_VERSION", "DRAFT").strip() or "DRAFT"
    tier = os.environ.get("GUARDRAIL_TIER", "").strip()
    if not tier and guardrail_id and require_credentials:
        # Ask the guardrail rather than assume. Every record and every fixture is
        # stamped with this tier, and a guessed value silently mislabels the lot —
        # a CLASSIC measurement filed as STANDARD is worse than no measurement.
        tier = _read_tier(guardrail_id, region, version) or ""

    return Preflight(
        guardrail_id=guardrail_id,
        region=region,
        guardrail_version=version,
        tier=tier or "UNKNOWN",
        account_id=account_id,
    )


def _read_tier(guardrail_id: str, region: str, version: str) -> str | None:
    """The tier the guardrail actually reports, or None if it cannot be read.

    AWS returns this as `topicPolicy.tier.tierName` — **not** `tierConfig`, which
    is Terraform's name for the input and appears nowhere in the response.
    """
    try:
        import boto3
        from botocore.exceptions import BotoCoreError, ClientError
    except ImportError:  # pragma: no cover - boto3 is a hard dependency
        return None
    try:
        resp = boto3.client("bedrock", region_name=region).get_guardrail(
            guardrailIdentifier=guardrail_id, guardrailVersion=version
        )
    except (ClientError, BotoCoreError):
        # bedrock:GetGuardrail may not be granted. Not fatal: the tier is
        # reported as UNKNOWN rather than invented.
        return None
    for policy in ("topicPolicy", "contentPolicy"):
        name = resp.get(policy, {}).get("tier", {}).get("tierName")
        if name:
            return name
    return None


def _check_credentials(region: str, client_factory=None) -> str:
    """Confirm credentials resolve, without making a Bedrock call.

    sts:GetCallerIdentity is the cheapest possible proof, and it needs no
    Bedrock permission — so a credentials problem is never misreported as a
    guardrail problem.
    """
    try:
        import boto3
        from botocore.exceptions import BotoCoreError, ClientError
    except ImportError as exc:  # pragma: no cover - boto3 is a hard dependency
        raise PreflightError(f"boto3 is not installed: {exc}") from exc

    factory = client_factory or (lambda: boto3.client("sts", region_name=region))
    try:
        return factory().get_caller_identity()["Account"]
    except (ClientError, BotoCoreError) as exc:
        raise PreflightError(
            f"AWS credentials are not usable in {region}: {type(exc).__name__}: {exc}\n"
            "Configure them with:\n  aws configure   (or set AWS_PROFILE)"
        ) from exc


def validate_prompt(prompt: str) -> str:
    """Reject an empty or over-long prompt before spending an AWS call."""
    stripped = prompt.strip()
    if not stripped:
        raise PromptError("prompt is empty after trimming whitespace")
    if len(stripped) > MAX_PROMPT_CHARS:
        raise PromptError(
            f"prompt is {len(stripped)} characters, over the {MAX_PROMPT_CHARS}-character limit"
        )
    return stripped


@dataclass
class Observation:
    """One evaluation of one prompt: what the guardrail did, and what it found."""

    prompt: str
    intervened: bool
    findings: list[PolicyHit] = field(default_factory=list)
    latency_ms: int = 0
    model_invoked: bool = False
    forwarded_text: str | None = None
    raw: dict[str, Any] | None = None

    @property
    def action(self) -> str:
        """The guardrail action, in the vocabulary AWS uses."""
        return "GUARDRAIL_INTERVENED" if self.intervened else "NONE"

    def policy_names(self) -> list[str]:
        return [f.detail for f in self.findings if f.detail]

    def policy_types(self) -> list[str]:
        return [f.policy for f in self.findings]


def build_service(pf: Preflight, client=None) -> GuardrailService:
    return GuardrailService(pf.settings, client=client)


def evaluate_prompt(service: GuardrailService, prompt: str) -> Observation:
    """Screen one prompt. No foundation model is invoked, by construction."""
    started = time.perf_counter()
    result: StageResult = service.screen(prompt)
    return Observation(
        prompt=prompt,
        intervened=result.intervened,
        findings=list(result.hits),
        latency_ms=result.latency_ms or int((time.perf_counter() - started) * 1000),
        model_invoked=result.model_invoked,
        forwarded_text=result.text,
        raw=result.raw,
    )


def evaluate_answer(
    service: GuardrailService, question: str, answer: str, reference: str | None = None
) -> Observation:
    """Grounding-check a supplied answer. Also no model: the answer is given."""
    result: StageResult = service.verify(question, answer, reference)
    return Observation(
        prompt=question,
        intervened=result.intervened,
        findings=list(result.hits),
        latency_ms=result.latency_ms or 0,
        model_invoked=result.model_invoked,
        raw=result.raw,
    )


def aws_error_code(exc: Exception) -> str:
    """The AWS error code behind a failure, for reporting without a traceback."""
    cause = exc.cause if isinstance(exc, StageFailure) else exc
    response = getattr(cause, "response", None)
    if isinstance(response, dict):
        return response.get("Error", {}).get("Code", type(cause).__name__)
    return type(cause).__name__


def failed_operation(exc: Exception) -> str:
    """Which AWS operation failed, named as the stage that called it."""
    if isinstance(exc, StageFailure):
        return {"screen": "ApplyGuardrail(INPUT)", "verify": "ApplyGuardrail(OUTPUT)"}.get(
            exc.stage, exc.stage
        )
    return "ApplyGuardrail"
