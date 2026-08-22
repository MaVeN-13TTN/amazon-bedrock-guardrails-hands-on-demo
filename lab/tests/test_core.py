"""Preflight, prompt validation and the evaluate subcommand."""
from __future__ import annotations

import pytest
from botocore.exceptions import ClientError

from lab.core import (
    MAX_PROMPT_CHARS,
    PreflightError,
    PromptError,
    aws_error_code,
    build_service,
    evaluate_prompt,
    failed_operation,
    preflight,
    validate_prompt,
)
from lab.evaluate import format_observation
from lab.tests.conftest import FakeBedrock, RaisingBedrock

DOSING = "How many millilitres of fungicide do I put in a 20 litre knapsack?"


# --- preflight -------------------------------------------------------------

def test_missing_guardrail_id_names_the_variable_and_the_command(monkeypatch):
    monkeypatch.delenv("GUARDRAIL_ID", raising=False)
    monkeypatch.setenv("AWS_REGION", "eu-west-1")
    with pytest.raises(PreflightError) as exc:
        preflight()
    assert "GUARDRAIL_ID" in str(exc.value)
    assert "terraform" in str(exc.value)


def test_missing_region_names_the_variable(monkeypatch):
    monkeypatch.setenv("GUARDRAIL_ID", "g-1")
    monkeypatch.delenv("AWS_REGION", raising=False)
    monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)
    with pytest.raises(PreflightError) as exc:
        preflight()
    assert "AWS_REGION" in str(exc.value)


def test_unusable_credentials_are_reported_as_a_prerequisite(monkeypatch):
    monkeypatch.setenv("GUARDRAIL_ID", "g-1")
    monkeypatch.setenv("AWS_REGION", "eu-west-1")

    class NoCreds:
        def get_caller_identity(self):
            raise ClientError(
                {"Error": {"Code": "InvalidClientTokenId", "Message": "bad token"}},
                "GetCallerIdentity",
            )

    with pytest.raises(PreflightError) as exc:
        preflight(client_factory=NoCreds)
    assert "credentials" in str(exc.value)
    assert "aws configure" in str(exc.value)


def test_preflight_returns_the_resolved_environment(monkeypatch):
    monkeypatch.setenv("GUARDRAIL_ID", "g-1")
    monkeypatch.setenv("AWS_REGION", "eu-west-1")
    monkeypatch.setenv("GUARDRAIL_TIER", "CLASSIC")

    resolved = preflight(client_factory=lambda: _Sts("012345678901"))
    assert resolved.guardrail_id == "g-1"
    assert resolved.region == "eu-west-1"
    assert resolved.tier == "CLASSIC"
    assert resolved.account_id == "012345678901"
    assert resolved.settings.guardrail_active


def test_teardown_does_not_require_a_guardrail_id(monkeypatch):
    """Teardown finds the resource by name, so it works after the id is gone."""
    monkeypatch.delenv("GUARDRAIL_ID", raising=False)
    monkeypatch.setenv("AWS_REGION", "eu-west-1")
    resolved = preflight(require_guardrail=False, client_factory=lambda: _Sts("1"))
    assert resolved.guardrail_id == ""


class _Sts:
    def __init__(self, account):
        self.account = account

    def get_caller_identity(self):
        return {"Account": self.account}


# --- prompt validation -----------------------------------------------------

def test_empty_prompt_is_rejected_before_any_call():
    with pytest.raises(PromptError, match="empty"):
        validate_prompt("   ")


def test_over_long_prompt_names_the_limit():
    with pytest.raises(PromptError) as exc:
        validate_prompt("x" * (MAX_PROMPT_CHARS + 1))
    assert str(MAX_PROMPT_CHARS) in str(exc.value)


def test_a_prompt_at_the_limit_is_accepted():
    assert len(validate_prompt("x" * MAX_PROMPT_CHARS)) == MAX_PROMPT_CHARS


# --- evaluation ------------------------------------------------------------

def test_evaluate_reports_the_findings_and_no_model_call(pf):
    service = build_service(pf, client=FakeBedrock(blocked_prompts=[DOSING]))
    obs = evaluate_prompt(service, DOSING)

    assert obs.intervened
    assert obs.action == "GUARDRAIL_INTERVENED"
    assert obs.model_invoked is False
    assert obs.policy_names() == ["Agrochemical Dosing"]


def test_a_clean_prompt_states_that_no_policy_intervened(pf):
    service = build_service(pf, client=FakeBedrock())
    printed = format_observation(evaluate_prompt(service, "When do points open?"))

    # Stated explicitly: silence would leave an attendee unsure it ran.
    assert "no policy intervened" in printed
    assert "model invoked     no" in printed


def test_masking_shows_the_forwarded_text(pf):
    prompt = "I am Grace Wanjiku, has my payment gone out?"
    service = build_service(pf, client=FakeBedrock(masked_prompts=[prompt]))
    obs = evaluate_prompt(service, prompt)
    printed = format_observation(obs)

    # Masking IS an intervention — AWS returns GUARDRAIL_INTERVENED with
    # actionReason "Guardrail masked." (V-15). What distinguishes it from a block
    # is that every finding is ANONYMIZED and the rewritten text is returned, so
    # the request continues rather than being refused.
    assert obs.intervened is True
    assert [h.action for h in obs.findings] == ["ANONYMIZED"]
    assert obs.forwarded_text == "I am {NAME}"
    assert "text forwarded" in printed
    assert "masked part of the input" in printed


def test_findings_are_printed_with_policy_type_and_detail(pf):
    service = build_service(pf, client=FakeBedrock(blocked_prompts=[DOSING]))
    printed = format_observation(evaluate_prompt(service, DOSING))
    assert "denied topic" in printed
    assert "Agrochemical Dosing" in printed
    assert "BLOCKED" in printed


def test_an_aws_failure_names_the_operation_and_the_code(pf):
    error = ClientError(
        {"Error": {"Code": "AccessDeniedException", "Message": "no"}}, "ApplyGuardrail"
    )
    service = build_service(pf, client=RaisingBedrock(error))
    with pytest.raises(Exception) as exc:
        evaluate_prompt(service, "anything")

    assert aws_error_code(exc.value) == "AccessDeniedException"
    assert failed_operation(exc.value) == "ApplyGuardrail(INPUT)"


def test_the_lab_never_invokes_a_model(pf):
    """No Converse method exists on the stub; calling one would fail loudly."""
    client = FakeBedrock()
    service = build_service(pf, client=client)
    evaluate_prompt(service, "When do points open?")

    assert all(call["source"] == "INPUT" for call in client.apply_calls)
    assert not hasattr(client, "converse")


# --- the tier is read, not guessed (V-24) -----------------------------------


class _TierClient:
    """A bedrock control-plane stand-in returning the tier AWS reports."""

    def __init__(self, tier: str | None, raises: Exception | None = None):
        self.tier = tier
        self.raises = raises
        self.calls = 0

    def get_guardrail(self, **kw):
        self.calls += 1
        if self.raises is not None:
            raise self.raises
        policy = {"topics": []}
        if self.tier is not None:
            policy["tier"] = {"tierName": self.tier}
        return {"topicPolicy": policy}


def test_the_tier_is_read_from_the_guardrail(monkeypatch):
    """A guessed tier mislabels every record and fixture written (V-24)."""
    import lab.core as core

    asked: list[tuple] = []

    def fake_read(gid, region, version):
        asked.append((gid, region, version))
        return "CLASSIC"

    monkeypatch.setattr(core, "_read_tier", fake_read)
    monkeypatch.setattr(core, "_check_credentials", lambda region, factory=None: "1234")
    monkeypatch.setenv("GUARDRAIL_ID", "g-1")
    monkeypatch.setenv("AWS_REGION", "eu-west-1")
    monkeypatch.delenv("GUARDRAIL_TIER", raising=False)

    pf = core.preflight()
    assert pf.tier == "CLASSIC"
    assert asked == [("g-1", "eu-west-1", "DRAFT")]


def test_an_unreadable_tier_is_reported_as_unknown_not_as_standard(monkeypatch):
    """The old default was STANDARD, which silently mislabelled CLASSIC runs."""
    import lab.core as core

    monkeypatch.setattr(core, "_read_tier", lambda *a: None)
    monkeypatch.setattr(core, "_check_credentials", lambda region, factory=None: "1234")
    monkeypatch.setenv("GUARDRAIL_ID", "g-1")
    monkeypatch.setenv("AWS_REGION", "eu-west-1")
    monkeypatch.delenv("GUARDRAIL_TIER", raising=False)

    assert core.preflight().tier == "UNKNOWN"


def test_read_tier_finds_the_field_where_aws_puts_it(monkeypatch):
    """It is `topicPolicy.tier.tierName` — not `tierConfig`, which is Terraform's name."""
    import boto3

    import lab.core as core

    monkeypatch.setattr(boto3, "client", lambda *a, **k: _TierClient("STANDARD"))
    assert core._read_tier("g-1", "eu-west-1", "DRAFT") == "STANDARD"


def test_a_tier_the_sdk_dropped_reads_as_none_not_as_a_default(monkeypatch):
    """boto3 1.37.x parses the response and discards `tier`, silently (V-24).

    The correct response to an absent field is None — never a default — because a
    default is indistinguishable from a confirmed reading.
    """
    import boto3

    import lab.core as core

    monkeypatch.setattr(boto3, "client", lambda *a, **k: _TierClient(None))
    assert core._read_tier("g-1", "eu-west-1", "DRAFT") is None


def test_a_denied_get_guardrail_is_not_fatal(monkeypatch):
    """bedrock:GetGuardrail may not be granted; the tier is UNKNOWN, not a guess."""
    import boto3
    from botocore.exceptions import ClientError

    import lab.core as core

    denied = ClientError(
        {"Error": {"Code": "AccessDeniedException", "Message": "no"}}, "GetGuardrail"
    )
    monkeypatch.setattr(boto3, "client", lambda *a, **k: _TierClient(None, raises=denied))
    assert core._read_tier("g-1", "eu-west-1", "DRAFT") is None


def test_an_explicit_tier_override_wins_and_makes_no_call(monkeypatch):
    import lab.core as core

    monkeypatch.setenv("GUARDRAIL_ID", "g-1")
    monkeypatch.setenv("AWS_REGION", "eu-west-1")
    monkeypatch.setenv("GUARDRAIL_TIER", "CLASSIC")

    def refuse(*a, **k):
        raise AssertionError("an explicit GUARDRAIL_TIER must not trigger a read")

    monkeypatch.setattr(core, "_read_tier", refuse)
    assert core.preflight(require_credentials=False).tier == "CLASSIC"
