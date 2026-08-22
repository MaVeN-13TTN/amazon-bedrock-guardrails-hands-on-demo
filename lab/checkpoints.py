"""`lab-cli checkpoint` — did this attendee get the documented result for module N?

Distinct from the Conformance_Runner, which asks whether the whole case set still
behaves as published. They share `evaluate_prompt()` and the record schema so a
measurement from either is comparable.

The verdict vocabulary matters. *Not evaluated* is not *unmet*: an absent
credential is not a failed expectation, and conflating them would send an attendee
looking for a policy defect that is really a missing environment variable.
"""
from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass, field

from lab.core import Observation, PreflightError, aws_error_code, evaluate_answer, evaluate_prompt

CHECKPOINTS_PATH = pathlib.Path(__file__).resolve().parent / "checkpoints.json"
PROBABILISTIC_REPETITIONS = 5
PROBABILISTIC_THRESHOLD = 3


class CheckpointError(ValueError):
    """The checkpoint declarations are unreadable or inconsistent with the scenario."""


@dataclass
class Checkpoint:
    module: int
    number: int
    prompt: str
    command: str
    expect_action: str
    determinism: str
    troubleshooting_id: str
    expect_policy_type: str | None = None
    expect_policy_name: str | None = None
    answer: str | None = None
    validation: dict | None = None
    # Free text explaining a counter-intuitive expectation, shown to the attendee.
    note: str | None = None

    @property
    def expects_intervention(self) -> bool:
        return self.expect_action == "intervened"

    @property
    def repetitions(self) -> int:
        return PROBABILISTIC_REPETITIONS if self.determinism == "probabilistic" else 1


@dataclass
class CheckpointResult:
    checkpoint: Checkpoint
    verdict: str  # met | unmet | not_evaluated
    observations: list[Observation] = field(default_factory=list)
    missing_prerequisite: str | None = None
    reason: str | None = None

    @property
    def intervened_count(self) -> int:
        return sum(o.intervened for o in self.observations)

    @property
    def observed_action(self) -> str:
        if not self.observations:
            return "not evaluated"
        if len(self.checkpoint.repetitions * [0]) == 1:
            return self.observations[0].action
        return f"intervened in {self.intervened_count}/{len(self.observations)}"

    def observed_policies(self) -> list[tuple[str, str]]:
        return [
            (f.policy, f.detail or "(unnamed)")
            for obs in self.observations[:1]
            for f in obs.findings
        ]


def _scenario_policy_names(scenario_path: pathlib.Path | None = None) -> set[str]:
    """Every policy name the scenario declares, for validating expectations.

    A checkpoint expecting a topic that no longer exists would report unmet with no
    hint that the *expectation* is what is wrong.
    """
    from lab.core import SCENARIO_PATH

    data = json.loads((scenario_path or SCENARIO_PATH).read_text(encoding="utf-8"))
    names = {t["name"] for t in data["denied_topics"]}
    names |= set(data["blocked_words"])
    names |= {e["type"] for e in data["pii_entities"]}
    names |= {r["name"] for r in data["pii_regexes"]}
    names |= {f["type"] for f in data["content_filters"]}
    return names


def load_checkpoints(
    path: pathlib.Path | None = None,
    module: int | None = None,
    scenario_path: pathlib.Path | None = None,
) -> list[Checkpoint]:
    target = path or CHECKPOINTS_PATH
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise CheckpointError(f"checkpoints not found at {target}") from exc
    except json.JSONDecodeError as exc:
        raise CheckpointError(f"checkpoints at {target} are not valid JSON: {exc}") from exc

    known = _scenario_policy_names(scenario_path)
    checkpoints: list[Checkpoint] = []
    for entry in raw.get("modules", []):
        if module is not None and entry["module"] != module:
            continue
        for spec in entry.get("checkpoints", []):
            name = spec.get("expect_policy_name")
            if name and name not in known:
                raise CheckpointError(
                    f"module {entry['module']} checkpoint {spec['number']} expects policy "
                    f"{name!r}, which shared/scenario.json does not declare. Either the "
                    f"policy was renamed or the checkpoint is stale."
                )
            checkpoints.append(Checkpoint(module=entry["module"], **spec))

    if module is not None and not checkpoints:
        raise CheckpointError(f"no checkpoints declared for module {module}")
    return checkpoints


def _judge(cp: Checkpoint, observations: list[Observation]) -> tuple[str, str | None]:
    """Met, or unmet with the discrepancy named."""
    intervened = sum(o.intervened for o in observations)
    total = len(observations)

    if cp.determinism == "probabilistic":
        # 3 of 5: a classifier that fires 3 times in 5 is working as configured,
        # and calling that unmet would teach an attendee to distrust it.
        got = intervened if cp.expects_intervention else total - intervened
        if got >= PROBABILISTIC_THRESHOLD:
            return "met", f"{got}/{total} repetitions matched (3 of 5 required)"
        return "unmet", (
            f"expected {cp.expect_action} in at least {PROBABILISTIC_THRESHOLD} of {total} "
            f"repetitions, observed {got}"
        )

    matched = (intervened > 0) == cp.expects_intervention
    if not matched:
        observed = "intervened" if intervened else "not_intervened"
        return "unmet", f"expected {cp.expect_action}, observed {observed}"

    if cp.expect_policy_name:
        found = [f.detail for obs in observations for f in obs.findings]
        if cp.expect_policy_name not in found:
            return "unmet", (
                f"expected policy {cp.expect_policy_name!r}, "
                f"observed {found or 'no findings'}"
            )
    return "met", None


def verify_checkpoint(service, cp: Checkpoint) -> CheckpointResult:
    observations: list[Observation] = []
    for _ in range(cp.repetitions):
        try:
            if cp.answer:
                obs = evaluate_answer(service, cp.prompt, cp.answer)
            else:
                obs = evaluate_prompt(service, cp.prompt)
        except PreflightError as exc:
            return CheckpointResult(
                cp, "not_evaluated", observations, missing_prerequisite=str(exc)
            )
        except Exception as exc:  # noqa: BLE001 — an AWS failure is not an unmet expectation
            return CheckpointResult(
                cp,
                "not_evaluated",
                observations,
                missing_prerequisite=f"AWS call failed: {aws_error_code(exc)}",
            )
        observations.append(obs)

    verdict, reason = _judge(cp, observations)
    return CheckpointResult(cp, verdict, observations, reason=reason)


def run(service, module: int, path: pathlib.Path | None = None) -> int:
    checkpoints = load_checkpoints(path, module=module)
    print(f"module {module} — {len(checkpoints)} checkpoint(s)\n")

    results = [verify_checkpoint(service, cp) for cp in checkpoints]
    for result in results:
        cp = result.checkpoint
        mark = {"met": "met  ", "unmet": "UNMET", "not_evaluated": "n/a  "}[result.verdict]
        print(f"  {mark} checkpoint {cp.number}: {cp.prompt[:58]}")
        print(f"        observed action  {result.observed_action}")
        for policy, detail in result.observed_policies():
            print(f"        observed policy  {policy}: {detail}")
        if cp.note:
            print(f"        note  {cp.note}")
        if result.verdict == "unmet":
            print(f"        {result.reason}")
            print(f"        see troubleshooting entry {cp.troubleshooting_id} in docs/lab-guide.md")
        elif result.verdict == "not_evaluated":
            print(f"        not evaluated: {result.missing_prerequisite}")
        elif result.reason:
            print(f"        {result.reason}")

    met = sum(r.verdict == "met" for r in results)
    unmet = sum(r.verdict == "unmet" for r in results)
    not_evaluated = sum(r.verdict == "not_evaluated" for r in results)
    print(
        f"\nmodule {module}: {len(results)} evaluated · {met} met · {unmet} unmet "
        f"· {not_evaluated} not evaluated"
    )
    # A checkpoint that could not run is not a pass, so it also fails the status.
    return 0 if unmet == 0 and not_evaluated == 0 else 1
