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
