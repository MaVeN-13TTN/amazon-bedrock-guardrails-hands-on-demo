"""Emit the IAM policy an attendee needs, with their own account and Region in it.

`docs/aws-prerequisites.md` prints these policies with `REGION` and `ACCOUNT` as
placeholders and asks the reader to substitute both. That is four hand-edits
across two documents before the first AWS call, and a mistyped ARN fails as
`no identity-based policy allows`, which reads exactly like a missing grant.

So the CLI writes it out instead. With credentials, the account id comes from
`sts:GetCallerIdentity`; without, the placeholders are left in place and labelled,
because a policy that silently contains the wrong account is worse than one that
visibly needs editing.
"""
from __future__ import annotations

import json

HAIKU = "anthropic.claude-haiku-4-5-20251001-v1:0"

PLACEHOLDER_ACCOUNT = "ACCOUNT"


def _partition(region: str) -> str:
    if region.startswith("us-gov-"):
        return "aws-us-gov"
    if region.startswith("cn-"):
        return "aws-cn"
    return "aws"


def lab_policy(region: str, account: str, partition: str) -> dict:
    """The Lab_Path: one guardrail, ApplyGuardrail, no model access."""
    guardrail = f"arn:{partition}:bedrock:{region}:{account}:guardrail/*"
    profile = f"arn:{partition}:bedrock:{region}:{account}:guardrail-profile/*"
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "GuardrailLifecycle",
                "Effect": "Allow",
                "Action": [
                    "bedrock:CreateGuardrail",
                    "bedrock:CreateGuardrailVersion",
                    "bedrock:UpdateGuardrail",
                    "bedrock:DeleteGuardrail",
                    "bedrock:GetGuardrail",
                    "bedrock:ListGuardrails",
                ],
                "Resource": [guardrail, profile],
            },
            {
                # Terraform tags what it manages and reads tags back when it
                # refreshes. Without these three, `apply` works exactly once and
                # then neither re-plans nor destroys (V-13, V-28).
                "Sid": "GuardrailTags",
                "Effect": "Allow",
                "Action": [
                    "bedrock:TagResource",
                    "bedrock:UntagResource",
                    "bedrock:ListTagsForResource",
                ],
                "Resource": guardrail,
            },
            {
                # The Region is wildcarded on the *profile* deliberately. A guardrail
                # profile routes to any Region in its geography, and ApplyGuardrail must
                # be permitted on the profile object in every destination, not only the
                # source. Pin it to one Region and calls fail intermittently, naming a
                # Region you never asked for (V-09). The EU profile has seven
                # destinations; APAC has thirteen.
                "Sid": "ApplyGuardrail",
                "Effect": "Allow",
                "Action": ["bedrock:ApplyGuardrail"],
                "Resource": [
                    guardrail,
                    f"arn:{partition}:bedrock:*:{account}:guardrail-profile/*",
                ],
            },
        ],
    }


def model_policy(region: str, account: str, partition: str) -> dict:
    """The answer stage only. A profile resolves to a model, so both ARNs are needed."""
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "InvokeThroughGlobalProfile",
                "Effect": "Allow",
                "Action": ["bedrock:InvokeModel", "bedrock:Converse"],
                "Resource": [
                    f"arn:{partition}:bedrock:{region}:{account}:inference-profile/global.{HAIKU}",
                    f"arn:{partition}:bedrock:*::foundation-model/{HAIKU}",
                ],
            }
        ],
    }


def resolve_account(session=None) -> tuple[str, bool]:
    """(account id, resolved). Falls back to the placeholder rather than guessing."""
    try:
        import boto3

        client = (session or boto3.Session()).client("sts")
        return client.get_caller_identity()["Account"], True
    except Exception:  # noqa: BLE001 — no credentials is an expected path here
        return PLACEHOLDER_ACCOUNT, False


def render(region: str, *, deploy: bool = False, session=None) -> str:
    account, resolved = resolve_account(session)
    partition = _partition(region)
    out: list[str] = []

    if resolved:
        out.append(f"# Account {account}, Region {region} — ready to paste.\n")
    else:
        out.append(
            f"# Could not resolve your account id, so {PLACEHOLDER_ACCOUNT} is left in\n"
            f"# place below. Replace it, or run `aws sso login` and try again.\n"
        )

    out.append("# Lab_Path — one guardrail, ApplyGuardrail, no model access needed.")
    out.append(json.dumps(lab_policy(region, account, partition), indent=2))

    if deploy:
        out.append(
            "\n# The answer stage as well. Only needed if you want stage 2 to call a\n"
            "# model; the lab and its 15 checkpoints do not."
        )
        out.append(json.dumps(model_policy(region, account, partition), indent=2))
        out.append(
            "\n# Deploying the stack additionally needs iam:CreateRole, iam:PassRole and\n"
            "# the lambda/apigateway/amplify/logs/cloudwatch actions. Check yours with:\n"
            "#   python -m lab doctor --check-deploy"
        )

    return "\n".join(out) + "\n"
