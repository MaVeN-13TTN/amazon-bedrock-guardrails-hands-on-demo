"""`lab-cli teardown` — remove everything the Lab_Guide created.

Deliberately state-independent: it queries the Bedrock control plane and matches by
the guardrail name in `shared/scenario.json` rather than reading Terraform state.
An attendee who cloned, applied, then deleted the directory is a realistic case,
and "your state file is gone, good luck" is not an acceptable answer to a recurring
charge.
"""
from __future__ import annotations

import json
import time

MANUAL_REMOVAL = "aws bedrock delete-guardrail --guardrail-identifier {identifier}"
VERIFY_WINDOW_SECONDS = 60
VERIFY_INTERVAL_SECONDS = 5


def guardrail_name(scenario_path=None) -> str:
    from lab.core import SCENARIO_PATH

    data = json.loads((scenario_path or SCENARIO_PATH).read_text(encoding="utf-8"))
    return data["guardrail_name"]


def _find(client, name: str) -> list[dict]:
    """Every guardrail matching the scenario's name, across paginated results."""
    matches: list[dict] = []
    token = None
    while True:
        kwargs = {"nextToken": token} if token else {}
        page = client.list_guardrails(**kwargs)
        matches.extend(
            g for g in page.get("guardrails", []) if g.get("name") == name
        )
        token = page.get("nextToken")
        if not token:
            break
    return matches


def _still_present(client, name: str) -> list[dict]:
    try:
        return _find(client, name)
    except Exception:  # noqa: BLE001 — treat an unreadable list as inconclusive
        return []


def run(client, *, scenario_path=None, sleep=time.sleep, clock=time.monotonic) -> int:
    """Delete the guardrail and its versions, then verify. Safe to run twice."""
    name = guardrail_name(scenario_path)
    print(f"teardown — looking for guardrails named {name!r}\n")

    try:
        found = _find(client, name)
    except Exception as exc:  # noqa: BLE001
        print(f"  ERR  could not list guardrails: {type(exc).__name__}: {exc}")
        return 1

    if not found:
        # Not an error: an attendee who already tore down should be reassured,
        # not alarmed, and a repeated run must be safe.
        print(f"  ok   guardrail {name}: already absent")
        print("\nnothing to remove. Bedrock model access persists and carries no charge "
              "while unused.")
        return 0

    failures: list[tuple[str, str]] = []
    for guardrail in found:
        identifier = guardrail.get("id") or guardrail.get("guardrailId", "")
        try:
            client.delete_guardrail(guardrailIdentifier=identifier)
            print(f"  ok   guardrail {identifier}: delete requested")
        except Exception as exc:  # noqa: BLE001 — continue with the rest regardless
            code = getattr(exc, "response", {}).get("Error", {}).get(
                "Code", type(exc).__name__
            )
            print(f"  ERR  guardrail {identifier}: delete failed ({code})")
            failures.append((identifier, code))

    print(f"\nverifying removal (up to {VERIFY_WINDOW_SECONDS}s)")
    deadline = clock() + VERIFY_WINDOW_SECONDS
    remaining = _still_present(client, name)
    while remaining and clock() < deadline:
        sleep(VERIFY_INTERVAL_SECONDS)
        remaining = _still_present(client, name)

    if not remaining:
        print("  ok   guardrail: removed")
        print("\nteardown complete. Bedrock model access persists as an account setting "
              "and carries no charge while unused.")
        return 0 if not failures else 1

    for guardrail in remaining:
        identifier = guardrail.get("id") or guardrail.get("guardrailId", "")
        print(f"  STILL PRESENT  guardrail {identifier}")
        print(f"                 remove manually: {MANUAL_REMOVAL.format(identifier=identifier)}")
    return 1
