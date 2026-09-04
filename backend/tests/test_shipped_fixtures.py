"""The committed Replay_Mode fixtures, driven through the real pipeline.

This file exists because of two defects that every other test in the suite
missed, both for the same reason: every other test builds its own synthetic
fixtures, so nothing ever exercised what is actually committed under
`app/fixtures/replay/`.

  * The masking case — the demo's headline moment, and the segment the runbook
    marks "never cut" — replayed as a **refusal**. The recording was made in an
    account where `bedrock:InvokeModel` is denied, so the answer stage substituted
    a canned bulletin answer; that answer did not address the question asked, so
    the relevance check scored it 0.07 and blocked it. The guardrail was right;
    the fixture was a faithful recording of a broken run.

  * The national-ID case replayed as **blocked at screen**, because a masked
    request carrying `NONE`-action findings was misjudged as a block
    (validation log V-31).

The second one is why these tests POST to `/api/ask` rather than reading the
fixture's stored `stopped_at`. That field said `None` for the masking case while
the pipeline derived `verify` from the recorded stages — so a test that trusted
the field would have passed over a demo that was visibly broken. **Assert on the
response the audience sees, not on the recording it came from.**

The distinction between *unrecorded* and *recorded and wrong* is load-bearing,
and matches this repository's rule that a skip is never a pass:

  * no fixture for a prompt              -> **skip**, naming the record command
  * a fixture that refuses an in-scope prompt -> **fail**
"""
from __future__ import annotations

import json
import pathlib

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.guardrails import GuardrailService
from app.main import app, get_service, get_settings
from app.replay import ReplayStore, normalise

ROOT = pathlib.Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "backend" / "app" / "fixtures" / "replay"
CASES = ROOT / "lab" / "cases.json"

RECORD_HINT = "python -m lab conformance --record --set {case_set}"


def _case_sets() -> dict:
    return json.loads(CASES.read_text(encoding="utf-8"))


def _prompts(classification: str, expect: str | None = None) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for name, spec in _case_sets().items():
        if spec.get("classification") != classification:
            continue
        if expect is not None and spec.get("expect") != expect:
            continue
        for case in spec.get("cases", []):
            out.append((name, case["prompt"]))
    return out


@pytest.fixture(scope="module")
def replay_client() -> TestClient:
    """The real app, in Replay_Mode, over the committed fixtures.

    No credentials, no Region, no boto3 client — the same conditions
    `scripts/replay-check.sh` runs under.
    """
    settings = Settings(
        guardrail_id="",
        guardrail_enabled=True,
        replay_mode=True,
        replay_dir=str(FIXTURES),
        guardrail_tier="CLASSIC",
    )
    service = GuardrailService(settings)
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_service] = lambda: service
    yield TestClient(app)
    app.dependency_overrides.clear()


def _ask(client: TestClient, prompt: str, case_set: str):
    response = client.post("/api/ask", json={"input": prompt})
    if response.status_code == 409:
        pytest.skip(
            f"no recorded fixture for {case_set!r}: {prompt!r}\n"
            f"record it with: {RECORD_HINT.format(case_set=case_set)}"
        )
    assert response.status_code == 200, response.text
    return response.json()


def test_the_fixture_directory_is_committed():
    assert FIXTURES.is_dir(), f"no replay fixtures at {FIXTURES}"
    assert list(FIXTURES.glob("*.json")), "replay fixture directory is empty"


@pytest.mark.parametrize("case_set,prompt", _prompts("in_scope"))
def test_an_in_scope_prompt_is_never_refused(replay_client, case_set, prompt):
    """The member asked a legitimate question. They must get an answer.

    Masking is not refusing: a prompt whose personal data was replaced still
    continues, and `stopped_at` stays None. A fixture in which an in-scope prompt
    ends at `screen`, `answer` or `verify` shows an audience the opposite of what
    the segment claims.
    """
    body = _ask(replay_client, prompt, case_set)
    assert body["stopped_at"] is None, (
        f"the {case_set!r} fixture refuses an in-scope prompt at stage "
        f"{body['stopped_at']!r}.\n"
        f"  prompt: {prompt}\n"
        f"  final:  {body['final'][:140]}\n"
        f"A member asking this is entitled to an answer. Re-record against a live "
        f"guardrail: {RECORD_HINT.format(case_set=case_set)}"
    )
    assert [s["stage"] for s in body["stages"]] == ["screen", "answer", "verify"]


@pytest.mark.parametrize("case_set,prompt", _prompts("violating", expect="blocked"))
def test_a_violating_prompt_is_always_stopped(replay_client, case_set, prompt):
    """The other direction, so a fix for the above cannot pass everything.

    Restricted to sets declaring `expect: "blocked"`. The `tier_gap` set declares
    `"blocked on STANDARD only"` and is deliberately excluded: at CLASSIC that
    Swahili prompt trips no policy at all, and a fixture recording it as allowed
    is the tier-gap lesson working, not a defect (V-26).
    """
    body = _ask(replay_client, prompt, case_set)
    assert body["stopped_at"] is not None, (
        f"the {case_set!r} fixture lets a violating prompt through:\n  {prompt}"
    )


def test_every_committed_fixture_is_still_a_declared_case():
    """A fixture whose prompt no longer appears in cases.json is stale.

    Changing a prompt in `lab/cases.json` without re-recording leaves a fixture
    keyed to text nobody will type, and Replay_Mode answers the new prompt with a
    409 — which reads to a presenter as "this prompt was never recorded" rather
    than "this fixture was orphaned by an edit".
    """
    declared = set()
    for spec in _case_sets().values():
        for key in ("cases", "in_scope_cases", "violating_cases"):
            for case in spec.get(key, []):
                declared.add(normalise(case["prompt"]))

    committed = ReplayStore(FIXTURES, tier="CLASSIC")._cases
    orphans = sorted(c.prompt for key, c in committed.items() if key not in declared)
    assert not orphans, (
        "these committed fixtures are keyed to prompts no longer in lab/cases.json:\n  "
        + "\n  ".join(repr(p) for p in orphans)
        + "\nRe-record them, or delete the stale fixture."
    )
