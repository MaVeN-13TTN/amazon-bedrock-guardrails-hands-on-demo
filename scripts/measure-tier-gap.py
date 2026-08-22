#!/usr/bin/env python
"""Create the scenario's guardrail directly, under a chosen tier, with no tags.

Why this exists: `terraform apply` cannot create a guardrail in an account lacking
`bedrock:TagResource`, because Terraform tags every resource it manages
(validation log V-13). The three tag permissions are an IAM grant nobody had
available, which left the STANDARD tier — and therefore the tier-gap measurement,
the demo's headline claim — unmeasurable.

`CreateGuardrail` itself does not require tagging. So this builds the *same*
policy from the *same* `shared/scenario.json` and omits only the tags, purely to
get a STANDARD-tier guardrail to measure against.

This is a measurement instrument, not a deployment path. Terraform remains the
only supported way to create this guardrail (ADR decision 5): the resource this
makes is untagged, unmanaged, and deleted by `--delete`.
"""
from __future__ import annotations

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "backend"))

import boto3
from botocore.exceptions import ClientError

from app import scenario

NAME_SUFFIX = {"CLASSIC": "-classic", "STANDARD": "-standard"}


def _policies(tier: str) -> dict:
    """Build the guardrail policy set from scenario.json, mirroring guardrail.tf."""
    raw = scenario.RAW
    tier_cfg = {"tierName": tier}

    return {
        "topicPolicyConfig": {
            "topicsConfig": [
                {
                    "name": t["name"],
                    "definition": t["definition"],
                    "examples": t.get("examples", []),
                    "type": "DENY",
                }
                for t in raw["denied_topics"]
            ],
            "tierConfig": tier_cfg,
        },
        "contentPolicyConfig": {
            "filtersConfig": [
                {
                    "type": f["type"],
                    "inputStrength": f["input_strength"],
                    "outputStrength": f["output_strength"],
                }
                for f in raw["content_filters"]
            ],
            "tierConfig": tier_cfg,
        },
        "wordPolicyConfig": {
            "wordsConfig": [{"text": w} for w in raw["blocked_words"]],
            "managedWordListsConfig": [{"type": "PROFANITY"}],
        },
        "sensitiveInformationPolicyConfig": {
            "piiEntitiesConfig": [
                {"type": e["type"], "action": e["action"],
                 "inputAction": e["action"], "outputAction": e["action"],
                 "inputEnabled": True, "outputEnabled": True}
                for e in raw["pii_entities"]
            ],
            "regexesConfig": [
                {"name": r["name"], "description": r["description"],
                 "pattern": r["pattern"], "action": r["action"],
                 "inputAction": r["action"], "outputAction": r["action"],
                 "inputEnabled": True, "outputEnabled": True}
                for r in raw["pii_regexes"]
            ],
        },
        "contextualGroundingPolicyConfig": {
            "filtersConfig": [
                {"type": "GROUNDING", "threshold": raw["grounding_threshold"],
                 "action": "BLOCK", "enabled": True},
                {"type": "RELEVANCE", "threshold": raw["relevance_threshold"],
                 "action": "BLOCK", "enabled": True},
            ]
        },
    }


def create(client, tier: str, region: str) -> str:
    kwargs = {
        "name": scenario.RAW["guardrail_name"] + NAME_SUFFIX[tier],
        "description": f"Tier-gap measurement, {tier}. Untagged; created outside Terraform.",
        "blockedInputMessaging": scenario.BLOCKED_INPUT_MESSAGE,
        "blockedOutputsMessaging": scenario.BLOCKED_OUTPUT_MESSAGE,
        **_policies(tier),
    }
    if tier == "STANDARD":
        # STANDARD requires cross-Region inference, addressed by a guardrail
        # profile ARN — not the bare profile id, which the provider rejects (V-05).
        account = boto3.client("sts", region_name=region).get_caller_identity()["Account"]
        prefix = region.split("-")[0]
        kwargs["crossRegionConfig"] = {
            "guardrailProfileIdentifier":
                f"arn:aws:bedrock:{region}:{account}:guardrail-profile/{prefix}.guardrail.v1:0"
        }

    resp = client.create_guardrail(**kwargs)
    return resp["guardrailId"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tier", choices=["CLASSIC", "STANDARD"], required=True)
    ap.add_argument("--region", default="eu-west-1")
    ap.add_argument("--delete", metavar="ID", help="delete a guardrail this script created")
    args = ap.parse_args()

    client = boto3.client("bedrock", region_name=args.region)

    if args.delete:
        client.delete_guardrail(guardrailIdentifier=args.delete)
        print(f"deleted {args.delete}")
        return 0

    try:
        gid = create(client, args.tier, args.region)
    except ClientError as exc:
        print(f"FAILED {args.tier}: {exc}", file=sys.stderr)
        return 1

    reported = client.get_guardrail(guardrailIdentifier=gid, guardrailVersion="DRAFT")
    print(f"created  {gid}")
    print(f"status   {reported['status']}")
    print(f"tier     topicPolicy={reported.get('topicPolicy', {}).get('tier')}")
    print(f"         contentPolicy={reported.get('contentPolicy', {}).get('tier')}")
    print(f"\nexport GUARDRAIL_ID={gid}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
