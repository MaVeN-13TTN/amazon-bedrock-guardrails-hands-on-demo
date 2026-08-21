"""Request and response models. These define the contract the frontend codes against."""
from typing import Any, Literal

from pydantic import BaseModel, Field

Stage = Literal["screen", "answer", "verify"]


class PolicyHit(BaseModel):
    """One policy that fired during an assessment."""

    policy: str = Field(description="human-readable policy name, e.g. 'denied topic'")
    detail: str | None = Field(default=None, description="which topic, type or regex")
    action: str | None = Field(default=None, description="BLOCKED, ANONYMIZED or NONE")
    where: Literal["input", "output"]
    score: float | str | None = None
    threshold: float | None = None
    passed: bool | None = Field(
        default=None, description="set for grounding/relevance, which score rather than match"
    )


class StageResult(BaseModel):
    stage: Stage
    intervened: bool
    hits: list[PolicyHit] = []
    text: str | None = Field(default=None, description="text after any masking")
    reason: str | None = None
    stop_reason: str | None = None
    model_invoked: bool = Field(
        default=False, description="whether this stage called a foundation model"
    )
    latency_ms: int | None = None
    raw: dict[str, Any] | None = Field(default=None, description="unmodified AWS assessment")


class AskRequest(BaseModel):
    input: str = Field(min_length=1, max_length=4000)


class AskResponse(BaseModel):
    stages: list[StageResult]
    final: str
    stopped_at: Stage | None = Field(
        default=None, description="stage that halted the request, if any"
    )
    total_latency_ms: int


class VerifyRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    answer: str = Field(min_length=1, max_length=4000)
    reference: str | None = Field(
        default=None, description="overrides the bulletin as grounding_source"
    )


class ContextResponse(BaseModel):
    org: str
    assistant: str
    county: str
    region: str
    model: str
    guardrail_id: str | None
    guardrail_version: str | None
    guardrail_active: bool
    bulletin: str
    denied_topics: list[str]
    blocked_words: list[str]
    grounding_threshold: float
    relevance_threshold: float


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    guardrail_active: bool
    region: str
