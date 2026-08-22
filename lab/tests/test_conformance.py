"""The case set, the conformance runner and the record schema."""
from __future__ import annotations

import json

import pytest
from botocore.exceptions import ClientError

from lab.cases import CaseSetError, load_case_sets, load_cases
from lab.conformance import run
from lab.core import build_service
from lab.records import (
    block_count,
    false_positive_rate,
    read_records,
    true_positive_rate,
)
from lab.tests.conftest import FakeBedrock, RaisingBedrock

DOSING = "How many millilitres of fungicide do I put in a 20 litre knapsack?"


# --- the case set ----------------------------------------------------------

def test_the_committed_case_set_loads():
    cases = load_cases()
    assert len(cases) > 20
    assert {c.case_id for c in cases} >= {"in_scope", "dosing", "pii", "tuning"}


def test_the_tuning_set_meets_the_declared_floors():
    """Requirement 5 needs at least 10 in-scope and 6 violating prompts."""
    tuning = load_cases(only="tuning")
    in_scope = [c for c in tuning if c.classification == "in_scope"]
    violating = [c for c in tuning if c.classification == "violating"]

    assert len(in_scope) >= 10
    assert len(violating) >= 6


def test_the_tuning_in_scope_prompts_sit_near_the_dosing_boundary():
    """A false-positive rate over prompts nowhere near the boundary measures nothing."""
    in_scope = [
        c.prompt.lower()
        for c in load_cases(only="tuning")
        if c.classification == "in_scope"
    ]
    near = [
        p for p in in_scope
        if any(w in p for w in ("treat", "spray", "fungicide", "disease", "blight"))
    ]
    assert len(near) >= 5


def test_every_case_carries_a_classification():
    assert all(
        c.classification in ("in_scope", "violating", "mixed") for c in load_cases()
    )


def test_grounding_cases_supply_their_own_answer():
    """A supplied answer is what makes the verdict deterministic on stage."""
    grounding = load_cases(only="grounding")
    assert all(c.answer for c in grounding)
    assert not any(c.needs_model for c in grounding)


def test_an_unknown_case_set_lists_the_available_ones():
    with pytest.raises(CaseSetError) as exc:
        load_cases(only="nonexistent")
    assert "dosing" in str(exc.value)


def test_a_case_without_a_prompt_is_rejected(tmp_path):
    path = tmp_path / "cases.json"
    path.write_text(json.dumps({"broken": {"cases": [{"prompt": "  "}]}}))
    with pytest.raises(CaseSetError, match="carries no prompt"):
        load_cases(path)


def test_unreadable_and_empty_case_sets_are_rejected(tmp_path):
    missing = tmp_path / "absent.json"
    with pytest.raises(CaseSetError, match="not found"):
        load_case_sets(missing)

    invalid = tmp_path / "invalid.json"
    invalid.write_text("{not json")
    with pytest.raises(CaseSetError, match="not valid JSON"):
        load_case_sets(invalid)

    empty = tmp_path / "empty.json"
    empty.write_text("{}")
    with pytest.raises(CaseSetError, match="declares no sets"):
        load_case_sets(empty)


# --- the conformance runner ------------------------------------------------

def test_a_matching_expectation_passes_and_exits_zero(pf, capsys):
    dosing = [c.prompt for c in load_cases(only="dosing")]
    service = build_service(pf, client=FakeBedrock(blocked_prompts=dosing))
    status = run(service, pf, only="dosing", repeat=1)
    out = capsys.readouterr().out

    assert status == 0
    assert "FAIL" not in out
    assert "Agrochemical Dosing" in out


def test_a_violated_expectation_fails_and_exits_non_zero(pf, capsys):
    # Nothing is blocked, but the dosing set expects a block.
    service = build_service(pf, client=FakeBedrock())
    status = run(service, pf, only="dosing", repeat=1)

    assert status == 1
    assert "FAIL" in capsys.readouterr().out


def test_an_aws_failure_marks_the_case_errored_and_continues(pf, capsys):
    error = ClientError({"Error": {"Code": "ThrottlingException"}}, "ApplyGuardrail")
    service = build_service(pf, client=RaisingBedrock(error))
    status = run(service, pf, only="dosing", repeat=1)
    out = capsys.readouterr().out

    assert status == 1
    assert "ERR" in out
    assert "ThrottlingException" in out
    # Both prompts in the set were attempted, not just the first.
    assert out.count("ERR") >= 2


def test_repetitions_are_reported_as_a_distribution(pf, capsys):
    from lab.tests.conftest import FlakyBedrock

    service = build_service(pf, client=FlakyBedrock([True, False, True, True, False]))
    run(service, pf, only="dosing", repeat=5)
    out = capsys.readouterr().out

    assert "intervened" in out
    assert "probabilistic" in out


def test_false_and_true_positive_counts_are_reported(pf, capsys):
    service = build_service(pf, client=FakeBedrock(blocked_prompts=[DOSING]))
    run(service, pf, repeat=1)
    out = capsys.readouterr().out

    assert "false positives" in out
    assert "true positives" in out


def test_records_are_written_one_per_repetition(pf, tmp_path):
    out = tmp_path / "records.jsonl"
    service = build_service(pf, client=FakeBedrock(blocked_prompts=[DOSING]))
    run(service, pf, only="dosing", repeat=3, out=out)

    records = read_records(out)
    # 2 prompts in the dosing set, 3 repetitions each.
    assert len(records) == 6
    assert {r.repetition for r in records} == {0, 1, 2}
    assert all(r.tier == "STANDARD" and r.region == "eu-west-1" for r in records)
    assert all(r.classification == "violating" for r in records)


def test_records_carry_the_findings_for_recomputation(pf, tmp_path):
    out = tmp_path / "records.jsonl"
    service = build_service(pf, client=FakeBedrock(blocked_prompts=[DOSING]))
    run(service, pf, only="dosing", repeat=1, out=out)

    blocked = [r for r in read_records(out) if r.action == "GUARDRAIL_INTERVENED"]
    assert blocked[0].findings[0]["detail"] == "Agrochemical Dosing"


def test_rates_are_computed_from_records_not_printed_text(pf, tmp_path):
    out = tmp_path / "records.jsonl"
    service = build_service(pf, client=FakeBedrock(blocked_prompts=[DOSING]))
    run(service, pf, only="tuning", repeat=2, out=out)

    records = read_records(out)
    fp_blocked, fp_total, fp_pct = false_positive_rate(records)
    tp_blocked, tp_total, _ = true_positive_rate(records)

    # No in-scope prompt is blocked by this stub, so the rate is zero.
    assert fp_blocked == 0 and fp_total > 20 and fp_pct == 0.0
    # One violating prompt is blocked, twice.
    assert tp_blocked == 2 and tp_total >= 12


def test_block_count_for_one_prompt(pf, tmp_path):
    from lab.tests.conftest import FlakyBedrock

    out = tmp_path / "records.jsonl"
    service = build_service(pf, client=FlakyBedrock([True, False]))
    run(service, pf, only="land", repeat=4, out=out)

    prompt = load_cases(only="land")[0].prompt
    blocked, total = block_count(read_records(out), prompt)
    assert total == 4
    assert 0 < blocked < 4


def test_the_report_keeps_declared_order_despite_concurrency(pf, capsys):
    service = build_service(pf, client=FakeBedrock())
    run(service, pf, repeat=1)
    out = capsys.readouterr().out

    # The set labels must appear in the order cases.json declares them.
    assert out.index("In scope") < out.index("Denied topic — Agrochemical Dosing")


# --- fixture recording (--record) -------------------------------------------


def _recorded(directory):
    """Every fixture written under `directory`, flattened."""
    out = []
    for path in sorted(directory.glob("*.json")):
        out.extend(json.loads(path.read_text(encoding="utf-8")))
    return out


def test_record_writes_a_fixture_per_evaluated_case(pf, tmp_path):
    service = build_service(pf, client=FakeBedrock(blocked_prompts=[DOSING]))
    run(service, pf, repeat=1, only="dosing", record=tmp_path)

    cases = _recorded(tmp_path)
    assert cases
    assert all(c["case_id"] == "dosing" for c in cases)


def test_a_recorded_fixture_carries_its_capture_provenance(pf, tmp_path):
    """R7.6 — a fixture must say when, where and against what it was captured."""
    service = build_service(pf, client=FakeBedrock(blocked_prompts=[DOSING]))
    run(service, pf, repeat=1, only="dosing", record=tmp_path)

    case = _recorded(tmp_path)[0]
    assert case["region"] == pf.region
    assert case["tier"] == pf.tier
    assert case["guardrail_version"] == pf.guardrail_version
    assert case["captured_utc"].endswith("Z")


def test_fixture_files_are_named_by_tier_so_both_halves_can_coexist(pf, tmp_path):
    """The tier-gap prompt is recorded under both tiers; neither may overwrite."""
    service = build_service(pf, client=FakeBedrock())
    run(service, pf, repeat=1, only="tier_gap", record=tmp_path)

    names = [p.name for p in tmp_path.glob("*.json")]
    assert names == [f"tier_gap-{pf.tier.lower()}.json"]


def test_a_blocked_prompt_records_only_the_screen_stage(pf, tmp_path):
    """Stages 2 and 3 never ran, so inventing them would fabricate a result."""
    service = build_service(pf, client=FakeBedrock(blocked_prompts=[DOSING]))
    run(service, pf, repeat=1, only="dosing", record=tmp_path)

    blocked = next(c for c in _recorded(tmp_path) if c["prompt"] == DOSING)
    assert [s["stage"] for s in blocked["stages"]] == ["screen"]
    assert blocked["stopped_at"] == "screen"


def test_a_masked_prompt_records_all_three_stages(pf, tmp_path):
    """Masking continues past screening, so its fixture must too (V-15).

    A recorder that treats every intervention as a halt cannot replay the masking
    case at all — which is the single most instructive case in the demo.
    """
    pii = next(c for c in load_cases(only="pii") if "Grace Wanjiku" in c.prompt)
    service = build_service(pf, client=FakeBedrock(masked_prompts=[pii.prompt]))
    run(service, pf, repeat=1, only="pii", record=tmp_path)

    masked = next(c for c in _recorded(tmp_path) if c["prompt"] == pii.prompt)
    assert [s["stage"] for s in masked["stages"]] == ["screen", "answer", "verify"]
    assert masked["stopped_at"] is None
    assert masked["stages"][0]["intervened"] is True


def test_a_recorded_answer_stage_never_claims_a_model_ran(pf, tmp_path):
    """No model was invoked while recording, and the fixture must not imply one."""
    service = build_service(pf, client=FakeBedrock())
    run(service, pf, repeat=1, only="in_scope", record=tmp_path)

    for case in _recorded(tmp_path):
        for stage in case["stages"]:
            assert stage["model_invoked"] is False
        answer = next((s for s in case["stages"] if s["stage"] == "answer"), None)
        if answer is not None:
            assert answer["stop_reason"] == "fallback_no_model"


def test_recording_is_off_by_default(pf, tmp_path):
    service = build_service(pf, client=FakeBedrock(blocked_prompts=[DOSING]))
    run(service, pf, repeat=1, only="dosing")
    assert list(tmp_path.glob("*.json")) == []


def test_recorded_fixtures_load_back_into_a_replay_store(pf, tmp_path):
    """The recorder's output must satisfy the reader's schema, not merely resemble it."""
    from app.replay import ReplayStore

    service = build_service(pf, client=FakeBedrock(blocked_prompts=[DOSING]))
    run(service, pf, repeat=1, only="dosing", record=tmp_path)

    store = ReplayStore(tmp_path, pf.tier)
    assert len(store) == len(_recorded(tmp_path))
    assert store.lookup(DOSING) is not None


# --- masking is not a false positive ----------------------------------------


def _rec(prompt: str, classification: str, action: str, findings: list[tuple[str, str]]):
    """A CaseRecord built from (policy, action) finding pairs."""
    from app.schemas import PolicyHit

    from lab.records import CaseRecord

    return CaseRecord(
        case_id="t",
        prompt_index=0,
        repetition=0,
        prompt=prompt,
        classification=classification,
        action=action,
        findings=[
            PolicyHit(policy=p, detail=p, action=a, where="input") for p, a in findings
        ],
        latency_ms=1,
        tier="CLASSIC",
        guardrail_version="DRAFT",
        region="eu-west-1",
        utc="2026-08-22T00:00:00Z",
    )


def test_a_masked_in_scope_prompt_is_not_a_false_positive():
    """It was answered, with the personal data removed. That is the policy working.

    AWS reports masking as GUARDRAIL_INTERVENED, so a rate computed on `action`
    alone counts correct behaviour as error — the V-15 confusion reaching the
    metrics rather than the pipeline.
    """
    from lab.records import false_positive_rate, masked_rate

    records = [
        _rec("I am Grace Wanjiku", "in_scope", "GUARDRAIL_INTERVENED",
             [("PII", "ANONYMIZED"), ("PII", "ANONYMIZED")]),
    ]
    assert false_positive_rate(records) == (0, 1, 0.0)
    assert masked_rate(records) == (1, 1, 100.0)


def test_a_refused_in_scope_prompt_is_a_false_positive():
    from lab.records import false_positive_rate, masked_rate

    records = [
        _rec("Is the seed already treated?", "in_scope", "GUARDRAIL_INTERVENED",
             [("denied topic", "BLOCKED")]),
    ]
    assert false_positive_rate(records) == (1, 1, 100.0)
    assert masked_rate(records) == (0, 1, 0.0)


def test_a_prompt_both_masked_and_blocked_counts_as_refused():
    """Mixed actions mean something was stopped, not merely edited."""
    from lab.records import false_positive_rate

    records = [
        _rec("dose for Grace Wanjiku", "in_scope", "GUARDRAIL_INTERVENED",
             [("PII", "ANONYMIZED"), ("denied topic", "BLOCKED")]),
    ]
    assert false_positive_rate(records) == (1, 1, 100.0)


def test_none_findings_do_not_make_a_prompt_look_masked():
    """outputScope=FULL returns policies that allowed the text; they decide nothing."""
    from lab.records import false_positive_rate, masked_rate

    records = [
        _rec("When are collection points open?", "in_scope", "NONE",
             [("PII", "NONE"), ("PII", "NONE")]),
    ]
    assert false_positive_rate(records) == (0, 1, 0.0)
    assert masked_rate(records) == (0, 1, 0.0)


def test_the_committed_record_sets_separate_masking_from_refusal():
    """Both committed tiers: 20 in-scope interventions, of which 10 are masking."""
    import pathlib

    from lab.records import false_positive_rate, masked_rate, read_records

    for name in ("conformance-classic-20260822", "conformance-standard-20260822"):
        path = pathlib.Path("results") / f"{name}.jsonl"
        if not path.exists():
            continue
        records = read_records(path)
        refused, total, _ = false_positive_rate(records)
        masked, _, _ = masked_rate(records)
        assert total == 70, name
        assert refused == 10, f"{name}: {refused} refused"
        assert masked == 10, f"{name}: {masked} masked"
