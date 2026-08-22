"""Request and response models. These define the contract the frontend codes against."""
from typing import Any, Literal

from pydantic import BaseModel, Field

Stage = Literal["screen", "answer", "verify"]


class SectionText(BaseModel):
    """One titled section of Landing_Page prose, from scenario.json."""

    title: str
    body: str


class BulletinFacts(BaseModel):
    """Extension Bulletin 14, as structured facts rather than prose.

    The Landing_Page needs the collection and payment details as discrete values,
    but scenario.json must stay the single source of truth. So these are declared
    alongside the bulletin rather than regex-extracted from it, and scenario.py
    asserts at import that every string here appears verbatim in the bulletin.
    """

    collection_points: list[str]
    collection_opens: str
    collection_closes: str
    collection_days: list[str]
    gate_requirement: str
    payment_delay_days: int
    payment_release: str
    payment_note: str


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


class ReplayMeta(BaseModel):
    """Provenance of a stage result served from a recorded fixture.

    Present only under Replay_Mode. The Background_View shows the capture date
    and Region so the audience is never shown a recorded result as though live.
    """

    captured_utc: str = Field(description="UTC date the live response was recorded")
    region: str
    tier: str = Field(description="guardrail tier in force at capture")
    guardrail_version: str


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
    replayed: ReplayMeta | None = Field(
        default=None, description="set when this stage came from a fixture, not a live call"
    )


class AskRequest(BaseModel):
    # 2000 matches Settings.max_input_chars and the Chat_Window's own limit, so
    # one number governs validation, the service check and the UI. They disagreed
    # before: a 3000-character input passed validation and was then rejected by
    # the service with a 413 naming a limit the schema did not enforce.
    input: str = Field(min_length=1, max_length=2000)


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
    # Landing_Page content. The frontend holds no copy of any of this — every
    # word a member reads on the page arrives here from shared/scenario.json.
    bulletin_facts: BulletinFacts
    about_sections: list[SectionText]


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    guardrail_active: bool
    region: str
