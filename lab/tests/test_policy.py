"""`lab policy` — the IAM policy with the reader's own values already in it."""
from __future__ import annotations

import json

import pytest

from lab.policy import PLACEHOLDER_ACCOUNT, _partition, lab_policy, model_policy, render


class _Sts:
    def __init__(self, account: str):
        self.account = account

    def client(self, _service):
        return self

    def get_caller_identity(self):
        return {"Account": self.account}


class _NoCredentials:
    def client(self, _service):
        raise RuntimeError("Unable to locate credentials")


def test_the_lab_policy_needs_no_model_action():
    """The Lab_Path's whole claim is that it runs without model access."""
    doc = lab_policy("eu-west-1", "111122223333", "aws")
    actions = [a for s in doc["Statement"] for a in s["Action"]]

    assert "bedrock:ApplyGuardrail" in actions
    assert not any("InvokeModel" in a or "Converse" in a for a in actions)


def test_the_lab_policy_carries_the_three_tag_actions():
    """Without these, `apply` works once and then never plans again (V-13, V-28)."""
    doc = lab_policy("eu-west-1", "111122223333", "aws")
    actions = {a for s in doc["Statement"] for a in s["Action"]}

    assert {"bedrock:TagResource", "bedrock:UntagResource",
            "bedrock:ListTagsForResource"} <= actions


def test_the_model_policy_names_both_the_profile_and_the_foundation_model():
    """A profile resolves to a model, so permitting only the profile is not enough."""
    resources = model_policy("eu-west-1", "111122223333", "aws")["Statement"][0]["Resource"]

    assert any(":inference-profile/global." in r for r in resources)
    assert any(":foundation-model/" in r for r in resources)


@pytest.mark.parametrize("region,expected", [
    ("eu-west-1", "aws"),
    ("us-gov-west-1", "aws-us-gov"),
    ("cn-north-1", "aws-cn"),
])
def test_the_partition_follows_the_region(region, expected):
    """An ARN built with the wrong partition is rejected, not merely unauthorised."""
    assert _partition(region) == expected


def test_a_resolved_account_is_substituted():
    out = render("eu-west-1", session=_Sts("111122223333"))

    assert "111122223333" in out
    assert PLACEHOLDER_ACCOUNT not in out
    assert "ready to paste" in out


def test_an_unresolved_account_keeps_the_placeholder_and_says_so():
    """Silently emitting the wrong account is worse than visibly needing an edit."""
    out = render("eu-west-1", session=_NoCredentials())

    assert PLACEHOLDER_ACCOUNT in out
    assert "Could not resolve" in out


def test_the_rendered_policies_are_valid_json():
    out = render("eu-west-1", deploy=True, session=_Sts("111122223333"))

    # Every brace-delimited block parses.
    depth, start, found = 0, None, 0
    for i, ch in enumerate(out):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start is not None:
                json.loads(out[start:i + 1])
                found += 1
    assert found == 2, f"expected two policy documents, parsed {found}"


def test_deploy_mode_adds_the_model_policy_and_the_create_role_note():
    out = render("eu-west-1", deploy=True, session=_Sts("111122223333"))

    assert "bedrock:InvokeModel" in out
    assert "iam:CreateRole" in out
    assert "lab doctor --check-deploy" in out


def test_apply_guardrail_permits_the_profile_in_every_destination_region():
    """A profile routes across its geography; pinning one Region fails intermittently.

    This mirrors the policy in docs/aws-prerequisites.md, which wildcards the
    Region on the profile for exactly this reason (V-09).
    """
    doc = lab_policy("eu-west-1", "111122223333", "aws")
    apply_stmt = next(s for s in doc["Statement"] if s["Sid"] == "ApplyGuardrail")

    profile = next(r for r in apply_stmt["Resource"] if "guardrail-profile" in r)
    assert profile == "arn:aws:bedrock:*:111122223333:guardrail-profile/*"
