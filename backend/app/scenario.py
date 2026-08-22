"""The demo's domain, loaded from shared/scenario.json.

That file is the single source of truth: Terraform reads it with `jsondecode` to
build the guardrail, and this module reads it at runtime for the system prompt,
the reference bulletin and the blocked-request messages. There is no second copy
of the policy to drift out of step.

Highland Growers Co-operative, Kilimo Desk, Project Tumaini, Batch Ledger v2 and
Extension Bulletin 14 are invented for this demo.
"""
import json
import os
import pathlib

from app.schemas import BulletinFacts, SectionText

_CANDIDATES = [
    # Lambda: the packaging step copies the file next to the app package.
    pathlib.Path(__file__).resolve().parent.parent / "scenario.json",
    # Local development: read it from the repo.
    pathlib.Path(__file__).resolve().parents[2] / "shared" / "scenario.json",
]


def _load() -> dict:
    override = os.environ.get("SCENARIO_PATH")
    paths = [pathlib.Path(override)] if override else _CANDIDATES
    for path in paths:
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
    searched = ", ".join(str(p) for p in paths)
    raise FileNotFoundError(f"scenario.json not found. Searched: {searched}")


_DATA = _load()

# The parsed scenario, for callers that need the policy definition itself rather
# than the derived constants below — Terraform reads the same file, and
# scripts/measure-tier-gap.py builds a guardrail from it.
RAW = _DATA


def _iter_strings(value, path: str):
    """Yield (path, string) for every string nested anywhere under `value`.

    Non-strings are skipped rather than stringified: payment_delay_days is the
    integer 14 while the bulletin spells it "fourteen", so stringifying would
    produce a spurious failure. The prose claim is guarded instead by
    payment_release, which is a verbatim phrase.
    """
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, list):
        for i, item in enumerate(value):
            yield from _iter_strings(item, f"{path}[{i}]")
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _iter_strings(item, f"{path}.{key}")


def check_bulletin_facts(facts: dict, bulletin: str) -> None:
    """Raise ValueError if any fact string is absent from the bulletin.

    The Landing_Page presents these facts to a member as though read from the
    bulletin. If an edit to the bulletin leaves a fact behind, the page would
    state something the co-operative's own document does not — so this fails at
    import rather than misinforming a member on stage.
    """
    drifted = [
        (path, text)
        for path, text in _iter_strings(facts, "bulletin_facts")
        if text not in bulletin
    ]
    if drifted:
        detail = "; ".join(f"{path} = {text!r}" for path, text in drifted)
        raise ValueError(
            f"scenario.json: bulletin_facts no longer match extension_bulletin. "
            f"Absent from the bulletin: {detail}"
        )


ORG: str = _DATA["org"]
ASSISTANT: str = _DATA["assistant"]
COUNTY: str = _DATA["county"]
GUARDRAIL_NAME: str = _DATA["guardrail_name"]

SYSTEM_PROMPT: str = _DATA["system_prompt"]
EXTENSION_BULLETIN: str = _DATA["extension_bulletin"]

BLOCKED_INPUT_MESSAGE: str = _DATA["blocked_input_message"]
BLOCKED_OUTPUT_MESSAGE: str = _DATA["blocked_output_message"]

# Policy definitions. The backend only reads these for display on /api/context —
# the guardrail itself is created by Terraform from the same file.
DENIED_TOPICS: list[dict] = _DATA["denied_topics"]
CONTENT_FILTERS: list[dict] = _DATA["content_filters"]
BLOCKED_WORDS: list[str] = _DATA["blocked_words"]
PII_ENTITIES: list[dict] = _DATA["pii_entities"]
PII_REGEXES: list[dict] = _DATA["pii_regexes"]

GROUNDING_THRESHOLD: float = _DATA["grounding_threshold"]
RELEVANCE_THRESHOLD: float = _DATA["relevance_threshold"]

# Landing_Page content. Read only by GET /api/context; Terraform references
# neither block, so editing them cannot change the guardrail.
check_bulletin_facts(_DATA["bulletin_facts"], EXTENSION_BULLETIN)

BULLETIN_FACTS: BulletinFacts = BulletinFacts.model_validate(_DATA["bulletin_facts"])
ABOUT_SECTIONS: list[SectionText] = [
    SectionText.model_validate(s) for s in _DATA["about_sections"]
]
