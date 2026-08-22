"""The Checkpoint_Verifier and the Teardown_Script."""
from __future__ import annotations

import json

import pytest
from botocore.exceptions import ClientError

from lab.checkpoints import (
    CheckpointError,
    load_checkpoints,
    verify_checkpoint,
)
from lab.checkpoints import (
    run as run_checkpoint,
)
from lab.core import build_service
from lab.teardown import run as run_teardown
from lab.tests.conftest import (
    FakeBedrock,
    FakeBedrockControl,
    FlakyBedrock,
    RaisingBedrock,
)

DOSING = "How many millilitres of fungicide do I put in a 20 litre knapsack?"


# --- declarations ----------------------------------------------------------

def test_the_committed_checkpoints_load_and_cover_eight_modules():
    checkpoints = load_checkpoints()
    assert {c.module for c in checkpoints} == set(range(1, 9))


def test_every_module_declares_between_one_and_five_checkpoints():
    checkpoints = load_checkpoints()
    for module in range(1, 9):
        count = len([c for c in checkpoints if c.module == module])
        assert 1 <= count <= 5


def test_every_prompt_is_within_the_declared_length():
    assert all(len(c.prompt) <= 500 for c in load_checkpoints())


def test_every_checkpoint_names_a_troubleshooting_entry():
    assert all(c.troubleshooting_id for c in load_checkpoints())


def test_expected_policy_names_are_validated_against_the_scenario(tmp_path):
    """A renamed topic must break loudly, not produce a mystery unmet checkpoint."""
    stale = {
        "modules": [{
            "module": 1,
            "checkpoints": [{
                "number": 1,
                "prompt": "anything",
                "command": "lab-cli evaluate --prompt 'anything'",
                "expect_action": "intervened",
                "expect_policy_type": "denied topic",
                "expect_policy_name": "Fertiliser Rates",
                "determinism": "deterministic",
                "troubleshooting_id": "TS-01-1",
                "validation": None,
            }],
        }]
    }
    path = tmp_path / "checkpoints.json"
    path.write_text(json.dumps(stale))

    with pytest.raises(CheckpointError) as exc:
        load_checkpoints(path)
    assert "Fertiliser Rates" in str(exc.value)
    assert "renamed" in str(exc.value)


def test_an_unknown_module_is_rejected():
    with pytest.raises(CheckpointError, match="no checkpoints declared for module 99"):
        load_checkpoints(module=99)


# --- verdicts --------------------------------------------------------------

def test_a_met_deterministic_checkpoint(pf):
    cp = next(c for c in load_checkpoints(module=4))  # word filter, deterministic
    service = build_service(pf, client=FakeBedrock(blocked_prompts=[cp.prompt]))
    # The word-filter stub reports a topic finding, so name matching is what
    # distinguishes met from unmet here.
    result = verify_checkpoint(service, cp)
    assert result.verdict == "unmet"
    assert "Project Tumaini" in result.reason


def test_a_clean_prompt_meets_a_not_intervened_checkpoint(pf):
    cp = load_checkpoints(module=1)[0]
    service = build_service(pf, client=FakeBedrock())
    assert verify_checkpoint(service, cp).verdict == "met"


def test_an_unmet_checkpoint_reports_expected_and_observed(pf):
    cp = load_checkpoints(module=1)[0]  # expects no intervention
    service = build_service(pf, client=FakeBedrock(blocked_prompts=[cp.prompt]))
    result = verify_checkpoint(service, cp)

    assert result.verdict == "unmet"
    assert "expected not_intervened" in result.reason
    assert "observed intervened" in result.reason


def test_a_probabilistic_checkpoint_is_met_at_three_of_five(pf):
    cp = load_checkpoints(module=2)[0]  # probabilistic, expects intervention
    service = build_service(pf, client=FlakyBedrock([True, True, True, False, False]))
    result = verify_checkpoint(service, cp)

    assert len(result.observations) == 5
    assert result.verdict == "met"
    assert "3/5" in result.reason


def test_a_probabilistic_checkpoint_is_unmet_at_two_of_five(pf):
    cp = load_checkpoints(module=2)[0]
    service = build_service(pf, client=FlakyBedrock([True, True, False, False, False]))
    result = verify_checkpoint(service, cp)

    assert result.verdict == "unmet"
    assert "at least 3 of 5" in result.reason


def test_an_aws_failure_is_not_evaluated_rather_than_unmet(pf):
    """An absent prerequisite is not a failed expectation."""
    cp = load_checkpoints(module=1)[0]
    error = ClientError({"Error": {"Code": "AccessDeniedException"}}, "ApplyGuardrail")
    service = build_service(pf, client=RaisingBedrock(error))
    result = verify_checkpoint(service, cp)

    assert result.verdict == "not_evaluated"
    assert "AccessDeniedException" in result.missing_prerequisite


def test_the_module_summary_counts_every_verdict(pf, capsys):
    service = build_service(pf, client=FakeBedrock())
    run_checkpoint(service, 1)
    out = capsys.readouterr().out

    assert "module 1:" in out
    assert "met" in out and "unmet" in out and "not evaluated" in out


def test_an_unmet_checkpoint_names_its_troubleshooting_entry(pf, capsys):
    service = build_service(pf, client=FakeBedrock(blocked_prompts=[
        load_checkpoints(module=1)[0].prompt
    ]))
    status = run_checkpoint(service, 1)
    out = capsys.readouterr().out

    assert status == 1
    assert "TS-01-1" in out
    assert "docs/lab-guide.md" in out


def test_a_not_evaluated_checkpoint_fails_the_exit_status(pf):
    """It did not pass, so it must not be reported as success."""
    error = ClientError({"Error": {"Code": "ExpiredTokenException"}}, "ApplyGuardrail")
    service = build_service(pf, client=RaisingBedrock(error))
    assert run_checkpoint(service, 1) == 1


def test_verification_makes_no_write_call(pf):
    cp = load_checkpoints(module=1)[0]
    client = FakeBedrock()
    verify_checkpoint(build_service(pf, client=client), cp)

    assert all("source" in call for call in client.apply_calls)
    assert not hasattr(client, "create_guardrail")
    assert not hasattr(client, "update_guardrail")


# --- teardown --------------------------------------------------------------

def test_teardown_removes_the_guardrail_and_confirms(capsys):
    client = FakeBedrockControl([{"id": "gr-1", "name": "kilimo-desk-member-support"}])
    status = run_teardown(client, sleep=lambda _: None)
    out = capsys.readouterr().out

    assert status == 0
    assert client.deleted == ["gr-1"]
    assert "gr-1" in out
    assert "removed" in out


def test_teardown_is_safe_to_run_twice(capsys):
    client = FakeBedrockControl([])
    status = run_teardown(client, sleep=lambda _: None)
    out = capsys.readouterr().out

    assert status == 0
    assert "already absent" in out


def test_teardown_states_what_persists_after_removal(capsys):
    client = FakeBedrockControl([{"id": "gr-1", "name": "kilimo-desk-member-support"}])
    run_teardown(client, sleep=lambda _: None)
    out = capsys.readouterr().out

    assert "model access" in out
    assert "no charge" in out


def test_teardown_reports_a_failed_removal_with_its_error_code(capsys):
    error = ClientError({"Error": {"Code": "ConflictException"}}, "DeleteGuardrail")
    client = FakeBedrockControl(
        [{"id": "gr-1", "name": "kilimo-desk-member-support"}], delete_error=error
    )
    ticks = iter([0, 10, 30, 61, 61, 61])
    status = run_teardown(client, sleep=lambda _: None, clock=lambda: next(ticks))
    out = capsys.readouterr().out

    assert status == 1
    assert "ConflictException" in out


def test_teardown_prints_the_manual_command_when_a_resource_persists(capsys):
    client = FakeBedrockControl(
        [{"id": "gr-1", "name": "kilimo-desk-member-support"}], persist=True
    )
    ticks = iter([0, 10, 30, 61, 61, 61])
    status = run_teardown(client, sleep=lambda _: None, clock=lambda: next(ticks))
    out = capsys.readouterr().out

    assert status == 1
    assert "STILL PRESENT" in out
    assert "aws bedrock delete-guardrail --guardrail-identifier gr-1" in out


def test_teardown_ignores_guardrails_belonging_to_someone_else(capsys):
    """Matching by the scenario's name must not delete an unrelated guardrail."""
    client = FakeBedrockControl([{"id": "gr-other", "name": "someone-elses-guardrail"}])
    status = run_teardown(client, sleep=lambda _: None)

    assert status == 0
    assert client.deleted == []
    assert "already absent" in capsys.readouterr().out
