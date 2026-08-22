"""Replay_Mode: serve recorded pipeline results when AWS is unreachable.

The demanding requirement is that all three stages complete with **no AWS
credentials present and Bedrock unreachable**. That rules out any design where a
fixture patches a boto3 response mid-call, because client construction itself
would still be attempted and would still need a Region and a credential chain.

So the fixture layer sits *above* the boto3 client, inside `GuardrailService`:
when replay is active the client is never constructed at all.

Fixtures are recorded from live AWS responses by `python -m lab conformance
--record`, never hand-written, and each carries the date, Region, tier and
guardrail version it was captured under. The Background_View shows that
provenance, so a recorded result is never displayed as though it were live.
"""
from __future__ import annotations

import json
import logging
import pathlib
import re

from pydantic import BaseModel, Field

from app.schemas import Stage, StageResult

log = logging.getLogger(__name__)

# Trailing punctuation only. Internal punctuation is meaning-bearing — "HG-004182"
# and "0722135790." differ in exactly the character we want to drop from the end.
_TRAILING = re.compile(r"[\s.,;:!?]+$")
_WHITESPACE = re.compile(r"\s+")


def normalise(prompt: str) -> str:
    """Key a fixture by prompt, tolerating the ways a presenter retypes one.

    Lowercases, collapses runs of whitespace, and strips trailing punctuation, so
    "How many millilitres?" and "how many  millilitres" match the same case.
    """
    return _TRAILING.sub("", _WHITESPACE.sub(" ", prompt.strip().lower()))


class ReplayCase(BaseModel):
    """One recorded request, with the provenance of its capture."""

    case_id: str
    prompt: str
    stages: list[StageResult] = []
    final: str = ""
    stopped_at: Stage | None = None
    captured_utc: str = Field(description="UTC timestamp of the live call this came from")
    region: str
    tier: str = Field(description="guardrail tier in force at capture: CLASSIC or STANDARD")
    guardrail_version: str

    # Set only on grounding cases, which the Grounding_Tool matches on the
    # answer rather than on the member's prompt.
    answer: str | None = None


class ReplayStore:
    """Fixtures keyed by normalised prompt, loaded from a directory of JSON files.

    A case may declare a tier. Where two cases share a prompt and differ by tier —
    the tier-gap prompt is recorded under both — the one matching the configured
    tier wins. That is what lets the tier-gap segment be demonstrated from
    fixtures when the live swap cannot be made.
    """

    def __init__(self, directory: pathlib.Path, tier: str = "CLASSIC") -> None:
        self.directory = pathlib.Path(directory)
        self.tier = tier
        self._cases: dict[str, ReplayCase] = {}
        self._load()

    def _load(self) -> None:
        if not self.directory.is_dir():
            log.warning("replay directory does not exist: %s", self.directory)
            return
        for path in sorted(self.directory.glob("*.json")):
            if path.name == "answer_fallback.json":
                continue  # not a replay case; the answer-stage fallback owns it
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                log.warning("skipping unparseable replay fixture: %s", path)
                continue
            for record in raw if isinstance(raw, list) else [raw]:
                try:
                    case = ReplayCase.model_validate(record)
                except Exception:  # noqa: BLE001 — a malformed fixture must not break startup
                    log.warning("skipping invalid replay case in %s", path)
                    continue
                self._insert(case)

    def _insert(self, case: ReplayCase) -> None:
        key = normalise(case.prompt)
        existing = self._cases.get(key)
        # A case recorded under the configured tier always wins over one that was
        # not, regardless of load order.
        if existing is not None and existing.tier == self.tier and case.tier != self.tier:
            return
        self._cases[key] = case

    # --- lookup ------------------------------------------------------------

    def lookup(self, prompt: str) -> ReplayCase | None:
        return self._cases.get(normalise(prompt))

    def verify_case(self, question: str, answer: str) -> tuple[ReplayCase, StageResult] | None:
        """The Grounding_Tool path: match on the answer, which is what varies.

        The three grounding cases share a question and differ only in the answer
        supplied, so the answer is the discriminator here. The case is returned
        alongside the stage so the caller can attach its capture provenance.
        """
        target = normalise(answer)
        for case in self._cases.values():
            if case.answer is None or normalise(case.answer) != target:
                continue
            for stage in case.stages:
                if stage.stage == "verify":
                    return case, stage
        return None

    @property
    def case_ids(self) -> list[str]:
        return sorted({c.case_id for c in self._cases.values()})

    @property
    def prompts(self) -> list[str]:
        return [c.prompt for c in self._cases.values()]

    def __len__(self) -> int:
        return len(self._cases)
