"""`lab-cli conformance` — run the declared case set against a live guardrail.

This is what turns `lab/cases.json` from an expectation set into evidence. It also
emits one JSONL record per repetition, which is the substrate for every measured
number in `docs/results.md` and for the tuning measurement of Requirement 5.
"""
from __future__ import annotations

import concurrent.futures
import datetime as _dt
import json
import pathlib
from dataclasses import dataclass, field

from lab.cases import Case, load_cases
from lab.core import Observation, Preflight, aws_error_code, evaluate_answer, evaluate_prompt
from lab.records import CaseRecord, RecordWriter

# lab.core puts backend/ on sys.path, so these two must be imported after it.
from app import scenario  # noqa: E402  isort:skip
from app.guardrails import canned_answer  # noqa: E402  isort:skip

MAX_WORKERS = 8
VERDICTS = ("pass", "fail", "skip", "error")


def _utc_now() -> str:
    return _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class CaseOutcome:
    """The verdict for one case across all its repetitions."""

    case: Case
    verdict: str
    observations: list[Observation] = field(default_factory=list)
    reason: str | None = None
    # The verify stage, recorded only when building fixtures for a prompt that
    # passed screening. Not part of any verdict.
    verify: Observation | None = None

    @property
    def actions(self) -> list[str]:
        return [o.action for o in self.observations]

    @property
    def probabilistic(self) -> bool:
        """Did the same prompt produce different actions across repetitions?"""
        return len(set(self.actions)) > 1

    @property
    def intervened_count(self) -> int:
        return sum(o.intervened for o in self.observations)

    def distribution(self) -> str:
        total = len(self.observations)
        return f"{self.intervened_count}/{total} intervened" if total else "not evaluated"


def _judge(case: Case, observations: list[Observation]) -> tuple[str, str | None]:
    """Compare observed behaviour against the declared expectation.

    A probabilistic case passes on the majority: a denied-topic classification that
    fires 4 times in 5 is the policy working, not a failure, and reporting it as
    one would train an attendee to distrust a correct guardrail.
    """
    if not observations:
        return "error", "no observation recorded"

    intervened = sum(o.intervened for o in observations)
    majority = intervened * 2 > len(observations)

    if case.expect in ("blocked", "anonymized"):
        return ("pass", None) if majority else (
            "fail",
            f"expected {case.expect}, intervened in {intervened}/{len(observations)}",
        )
    if case.expect == "pass":
        return ("pass", None) if not majority else (
            "fail",
            f"expected no intervention, intervened in {intervened}/{len(observations)}",
        )
    # "mixed" and tier-conditional expectations are recorded, not judged: the
    # measurement is the output, and asserting one would prejudge the finding.
    return "pass", f"recorded: {intervened}/{len(observations)} intervened"


def _evaluate_case(service, case: Case, repeat: int, record: bool = False) -> CaseOutcome:
    if case.needs_model and not record:
        return CaseOutcome(
            case, "skip", reason="needs a live model answer; model access unavailable"
        )

    observations: list[Observation] = []
    for _ in range(repeat):
        try:
            if case.answer:
                obs = evaluate_answer(service, case.prompt, case.answer)
            else:
                obs = evaluate_prompt(service, case.prompt)
        except Exception as exc:  # noqa: BLE001 — reported per case, run continues
            return CaseOutcome(
                case, "error", observations, reason=aws_error_code(exc)
            )
        observations.append(obs)

    # Recording a prompt that passed screening: run the verify stage too, so the
    # fixture covers all three. Stage 3 needs no model — it grounds a supplied
    # answer — so the only answer available is the bulletin-grounded fallback,
    # which is what the fixture will serve anyway.
    verify_obs: Observation | None = None
    if record and not case.answer and observations and _continues(observations[0]):
        fallback = canned_answer(case.prompt)
        if fallback:
            try:
                verify_obs = evaluate_answer(service, case.prompt, fallback)
            except Exception:  # noqa: BLE001 — a fixture without stage 3 is still useful
                verify_obs = None

    verdict, reason = _judge(case, observations)
    if case.needs_model:
        # The screen stage ran and is worth recording, but this case's expectation
        # describes what the *model* does, which nothing here invoked. Report it as
        # skipped rather than let a screen result stand in for a confirmation.
        verdict = "skip"
        reason = "screen stage recorded; the answer-stage expectation needs model access"
    return CaseOutcome(case, verdict, observations, reason, verify=verify_obs)


def _masked_only(obs: Observation) -> bool:
    """Did the guardrail mask rather than block?

    The same distinction `main.py` makes, and for the same reason: AWS reports
    masking as `GUARDRAIL_INTERVENED`, so treating every intervention as a halt
    means a masked prompt never reaches stages 2 and 3 — which was the V-15 defect.
    A recorder that repeats the mistake produces fixtures that cannot replay the
    masking case at all.
    """
    return (
        obs.intervened
        and bool(obs.findings)
        and all(h.action == "ANONYMIZED" for h in obs.findings if h.action)
    )


def _continues(obs: Observation) -> bool:
    """Would the pipeline carry on past screening for this observation?"""
    return not obs.intervened or _masked_only(obs)


def _refused_obs(obs: Observation) -> bool:
    """Did the guardrail stop this request, as opposed to editing it?"""
    return obs.intervened and not _masked_only(obs)



def _fixture_case(
    outcome: CaseOutcome, pf: Preflight, final: str, stopped_at: str | None
) -> dict:
    """Build one Replay_Mode fixture from a live outcome.

    Recorded from the **first** repetition rather than an aggregate: a fixture has
    to be one real response, and averaging a probabilistic case would produce a
    result AWS never returned.
    """
    obs = outcome.observations[0]
    stage = "verify" if outcome.case.answer else "screen"
    stages: list[dict] = [
        {
            "stage": stage,
            "intervened": obs.intervened,
            "hits": [h.model_dump() for h in obs.findings],
            "text": obs.forwarded_text,
            "model_invoked": obs.model_invoked,
            "latency_ms": obs.latency_ms,
            "raw": obs.raw,
        }
    ]
    # A prompt that passed screening needs an answer for the Chat_Window to show.
    # No model was invoked here, so it comes from the same bulletin-grounded
    # fallback the answer stage uses, labelled as such — a fixture must not imply
    # a model spoke when none did.
    if stage == "screen" and _continues(obs):
        answer_text = canned_answer(outcome.case.prompt)
        if answer_text:
            stages.append(
                {
                    "stage": "answer",
                    "intervened": False,
                    "hits": [],
                    "text": answer_text,
                    "stop_reason": "fallback_no_model",
                    "model_invoked": False,
                    "latency_ms": 0,
                    "raw": {"info": "bulletin-grounded fallback; no model was invoked"},
                }
            )
        if outcome.verify is not None:
            stages.append(
                {
                    "stage": "verify",
                    "intervened": outcome.verify.intervened,
                    "hits": [h.model_dump() for h in outcome.verify.findings],
                    "model_invoked": outcome.verify.model_invoked,
                    "latency_ms": outcome.verify.latency_ms,
                    "raw": outcome.verify.raw,
                }
            )
    return {
        "case_id": outcome.case.case_id,
        "prompt": outcome.case.prompt,
        "answer": outcome.case.answer,
        "stages": stages,
        "final": final,
        "stopped_at": stopped_at,
        "captured_utc": _utc_now(),
        "region": pf.region,
        "tier": pf.tier,
        "guardrail_version": pf.guardrail_version,
    }


def _write_fixtures(outcomes: list[CaseOutcome], pf: Preflight, directory: pathlib.Path) -> int:
    """Write one fixture file per case set, keyed by tier.

    Files are named `<set>-<tier>.json` so recording under the other tier adds
    rather than overwrites — the tier-gap prompt needs both to exist at once.
    """
    directory.mkdir(parents=True, exist_ok=True)
    grouped: dict[str, list[dict]] = {}
    for outcome in outcomes:
        if not outcome.observations:
            continue  # skipped or errored: there is no live response to record
        case = outcome.case
        if case.answer:
            final, stopped_at = "", "verify" if outcome.observations[0].intervened else None
        elif not _continues(outcome.observations[0]):
            final, stopped_at = scenario.BLOCKED_INPUT_MESSAGE, "screen"
        else:
            # Masked as well as clean: a masked request continues, which is the
            # whole point of ANONYMIZE (validation log V-15).
            final, stopped_at = canned_answer(case.prompt), None
        grouped.setdefault(case.case_id, []).append(
            _fixture_case(outcome, pf, final, stopped_at)
        )

    written = 0
    for case_id, records in grouped.items():
        path = directory / f"{case_id}-{pf.tier.lower()}.json"
        path.write_text(
            json.dumps(records, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        written += len(records)
    return written


def run(
    service,
    pf: Preflight,
    *,
    repeat: int = 1,
    only: str | None = None,
    out: pathlib.Path | None = None,
    cases_path: pathlib.Path | None = None,
    record: pathlib.Path | None = None,
) -> int:
    """Evaluate every case, print a report, and return a process exit status."""
    cases = load_cases(cases_path, only=only)
    print(f"conformance — {len(cases)} prompts, {repeat} repetition(s) each")
    print(f"guardrail {pf.guardrail_id} v{pf.guardrail_version} · {pf.tier} · {pf.region}\n")

    outcomes: list[CaseOutcome] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {
            pool.submit(_evaluate_case, service, case, repeat, record is not None): case
            for case in cases
        }
        for future in concurrent.futures.as_completed(futures):
            outcomes.append(future.result())

    # Restore declared order; concurrency must not reorder a printed report.
    order = {(c.case_id, c.prompt_index): i for i, c in enumerate(cases)}
    outcomes.sort(key=lambda o: order[(o.case.case_id, o.case.prompt_index)])

    with RecordWriter(out) as writer:
        for outcome in outcomes:
            for repetition, obs in enumerate(outcome.observations):
                writer.write(
                    CaseRecord.build(
                        case_id=outcome.case.case_id,
                        prompt_index=outcome.case.prompt_index,
                        repetition=repetition,
                        classification=outcome.case.classification,
                        observation=obs,
                        tier=pf.tier,
                        guardrail_version=pf.guardrail_version,
                        region=pf.region,
                    )
                )

    _report(outcomes)
    if out:
        print(f"\nrecords written to {out}")
    if record:
        count = _write_fixtures(outcomes, pf, record)
        print(f"{count} Replay_Mode fixture(s) written to {record} (tier {pf.tier})")
        print("re-run under the other tier to record its half of the tier gap")

    failed = sum(o.verdict == "fail" for o in outcomes)
    errored = sum(o.verdict == "error" for o in outcomes)
    return 0 if failed == 0 and errored == 0 else 1


def _report(outcomes: list[CaseOutcome]) -> None:
    current = None
    for outcome in outcomes:
        case = outcome.case
        if case.case_id != current:
            current = case.case_id
            print(f"{case.label}")

        mark = {"pass": "ok  ", "fail": "FAIL", "skip": "skip", "error": "ERR "}[outcome.verdict]
        prompt = case.case_label or case.prompt
        print(f"  {mark} {prompt[:62]:<64} expect={case.expect:<12} {outcome.distribution()}")

        if outcome.probabilistic:
            print("       probabilistic — the action differed across repetitions")
        if outcome.reason:
            print(f"       {outcome.reason}")
        for finding in outcome.observations[0].findings if outcome.observations else []:
            print(f"       · {finding.policy}: {finding.detail} → {finding.action}")

    counts = {v: sum(o.verdict == v for o in outcomes) for v in VERDICTS}
    in_scope = [o for o in outcomes if o.case.classification == "in_scope"]
    violating = [o for o in outcomes if o.case.classification == "violating"]
    # Masking is not over-blocking. An in-scope prompt that was masked and then
    # answered is the policy working; counting it as a false positive inflates the
    # rate with correct behaviour (the V-15 confusion, reaching the metrics).
    refused = [o for o in in_scope if o.observations and _refused_obs(o.observations[0])]
    masked = [
        o for o in in_scope
        if o.observations and o.observations[0].intervened
        and _masked_only(o.observations[0])
    ]
    false_positives = len(refused)
    true_positives = sum(o.intervened_count > 0 for o in violating)

    print(
        f"\n{len(outcomes)} evaluated · {counts['pass']} passed · {counts['fail']} failed "
        f"· {counts['skip']} skipped · {counts['error']} errored"
    )
    print(
        f"false positives {false_positives}/{len(in_scope)} in-scope prompts refused · "
        f"true positives {true_positives}/{len(violating)} violating prompts intervened"
    )
    if masked:
        print(
            f"masked {len(masked)}/{len(in_scope)} in-scope prompts answered with data "
            "removed — not false positives"
    )
