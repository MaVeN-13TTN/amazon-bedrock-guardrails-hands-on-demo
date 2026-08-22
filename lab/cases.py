"""The case set, loaded from `lab/cases.json`.

The file moved here from `backend/tests/suite.json`, where pytest collected it and
it contained no executable assertion — it declared expectations that nothing ran.
Its name and location now say what it is.
"""
from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass

CASES_PATH = pathlib.Path(__file__).resolve().parent / "cases.json"

# Which stage a set exercises, and therefore whether a model answer is needed.
NEEDS_MODEL = frozenset({"screen+answer"})


class CaseSetError(ValueError):
    """The case set is unreadable or a case carries no prompt."""


@dataclass
class Case:
    """One prompt with its declared expectation."""

    case_id: str
    prompt_index: int
    prompt: str
    classification: str
    stage: str
    expect: str
    label: str
    policy: str | None = None
    answer: str | None = None
    case_label: str | None = None

    @property
    def needs_model(self) -> bool:
        """Does confirming this expectation require a live model answer?

        A `screen+answer` case declares an outcome that depends on what the model
        says, so screening alone cannot confirm it. A grounding case supplies its
        own answer, so it does not need one.
        """
        return self.stage in NEEDS_MODEL and self.answer is None

    @property
    def expects_intervention(self) -> bool:
        return self.expect in ("blocked", "anonymized")


def load_case_sets(path: pathlib.Path | None = None) -> dict[str, dict]:
    target = path or CASES_PATH
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise CaseSetError(f"case set not found at {target}") from exc
    except json.JSONDecodeError as exc:
        raise CaseSetError(f"case set at {target} is not valid JSON: {exc}") from exc
    if not isinstance(raw, dict) or not raw:
        raise CaseSetError(f"case set at {target} declares no sets")
    return raw


def load_cases(
    path: pathlib.Path | None = None, only: str | None = None
) -> list[Case]:
    """Flatten the case sets into individual cases, validating each has a prompt."""
    sets = load_case_sets(path)
    if only:
        if only not in sets:
            raise CaseSetError(
                f"no case set named {only!r}. Available: {', '.join(sorted(sets))}"
            )
        sets = {only: sets[only]}

    cases: list[Case] = []
    for case_id, spec in sets.items():
        declared = spec.get("classification", "mixed")
        # The tuning set splits its prompts by classification rather than
        # declaring one for the whole set.
        groups = [
            ("cases", declared),
            ("in_scope_cases", "in_scope"),
            ("violating_cases", "violating"),
        ]
        for key, classification in groups:
            for index, entry in enumerate(spec.get(key) or []):
                prompt = (entry.get("prompt") or "").strip()
                if not prompt:
                    raise CaseSetError(f"{case_id}[{key}][{index}] carries no prompt")
                cases.append(
                    Case(
                        case_id=case_id,
                        prompt_index=len(
                            [c for c in cases if c.case_id == case_id]
                        ),
                        prompt=prompt,
                        classification=classification,
                        stage=spec.get("stage", "screen"),
                        expect=entry.get("expect", spec.get("expect", "pass")),
                        label=spec.get("label", case_id),
                        policy=spec.get("policy"),
                        answer=entry.get("answer"),
                        case_label=entry.get("label"),
                    )
                )
    if not cases:
        raise CaseSetError("case set declares no prompts")
    return cases
