"""Machine-readable evaluation records.

Every measured number in the documentation is computed from these rather than
transcribed from printed output, so a claim in `docs/results.md` can be traced to
the repetition that produced it.
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib
from dataclasses import asdict, dataclass, field

from lab.core import Observation


def utc_now() -> str:
    return dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class CaseRecord:
    """One repetition of one prompt, with everything needed to recompute a claim."""

    case_id: str
    prompt_index: int
    repetition: int
    prompt: str
    classification: str  # "in_scope" | "violating" | "mixed"
    action: str  # GUARDRAIL_INTERVENED | NONE
    findings: list[dict] = field(default_factory=list)
    latency_ms: int = 0
    tier: str = "STANDARD"
    guardrail_version: str = "DRAFT"
    region: str = ""
    utc: str = field(default_factory=utc_now)

    @classmethod
    def build(
        cls,
        *,
        case_id: str,
        prompt_index: int,
        repetition: int,
        classification: str,
        observation: Observation,
        tier: str,
        guardrail_version: str,
        region: str,
    ) -> CaseRecord:
        return cls(
            case_id=case_id,
            prompt_index=prompt_index,
            repetition=repetition,
            prompt=observation.prompt,
            classification=classification,
            action=observation.action,
            findings=[
                {"policy": f.policy, "detail": f.detail, "action": f.action, "where": f.where}
                for f in observation.findings
            ],
            latency_ms=observation.latency_ms,
            tier=tier,
            guardrail_version=guardrail_version,
            region=region,
        )

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)


class RecordWriter:
    """Appends one JSON object per line. A no-op when no path was given."""

    def __init__(self, path: pathlib.Path | None):
        self.path = path
        self._handle = None
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)
            self._handle = path.open("w", encoding="utf-8")

    def write(self, record: CaseRecord) -> None:
        if self._handle:
            self._handle.write(record.to_json() + "\n")

    def close(self) -> None:
        if self._handle:
            self._handle.close()
            self._handle = None

    def __enter__(self) -> RecordWriter:
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def read_records(path: pathlib.Path) -> list[CaseRecord]:
    """Load records back, for computing rates over a completed run."""
    with path.open(encoding="utf-8") as handle:
        return [CaseRecord(**json.loads(line)) for line in handle if line.strip()]


def _masked_only(record: CaseRecord) -> bool:
    """Did this record mask rather than refuse?

    AWS reports masking as `GUARDRAIL_INTERVENED` with `actionReason: "Guardrail
    masked."`, so `action` alone cannot distinguish a refusal from a redaction —
    the same trap that produced the V-15 pipeline defect, and it reaches the
    metrics too. A masked in-scope prompt was *answered*, with personal data
    removed. Counting it as a false positive inflates the rate with the policy
    working exactly as designed.
    """
    # Findings arrive as PolicyHit when built in-process and as plain dicts when
    # read back from JSONL, so accept both rather than depending on which path
    # produced the record.
    actions = [
        a for f in record.findings
        if (a := f.get("action") if isinstance(f, dict) else f.action)
        and a != "NONE"
    ]
    return bool(actions) and all(a == "ANONYMIZED" for a in actions)


def _refused(record: CaseRecord) -> bool:
    """Did the guardrail stop this request, as opposed to editing it?"""
    return record.action == "GUARDRAIL_INTERVENED" and not _masked_only(record)


def false_positive_rate(records: list[CaseRecord]) -> tuple[int, int, float]:
    """(refused, evaluated, percent) over in-scope records only.

    An in-scope prompt is one whose answer is in the bulletin. **Refusing** it is
    the error this measures — the cost of a policy drawn too wide. A prompt that
    was masked and then answered is not an error, so it is excluded: see
    `_masked_only`.
    """
    in_scope = [r for r in records if r.classification == "in_scope"]
    refused = [r for r in in_scope if _refused(r)]
    if not in_scope:
        return 0, 0, 0.0
    return len(refused), len(in_scope), round(len(refused) / len(in_scope) * 100, 1)


def masked_rate(records: list[CaseRecord]) -> tuple[int, int, float]:
    """(masked, evaluated, percent) over in-scope records only.

    Reported separately from the false-positive rate because it is a different
    outcome: the member got their answer, and the model never saw their personal
    data.
    """
    in_scope = [r for r in records if r.classification == "in_scope"]
    masked = [r for r in in_scope if r.action == "GUARDRAIL_INTERVENED" and _masked_only(r)]
    if not in_scope:
        return 0, 0, 0.0
    return len(masked), len(in_scope), round(len(masked) / len(in_scope) * 100, 1)


def true_positive_rate(records: list[CaseRecord]) -> tuple[int, int, float]:
    """(blocked, evaluated, percent) over violating records only."""
    violating = [r for r in records if r.classification == "violating"]
    blocked = [r for r in violating if r.action == "GUARDRAIL_INTERVENED"]
    if not violating:
        return 0, 0, 0.0
    return len(blocked), len(violating), round(len(blocked) / len(violating) * 100, 1)


def block_count(records: list[CaseRecord], prompt: str) -> tuple[int, int]:
    """(blocked, repetitions) for one exact prompt, for a probabilistic claim."""
    matching = [r for r in records if r.prompt == prompt]
    return sum(r.action == "GUARDRAIL_INTERVENED" for r in matching), len(matching)
