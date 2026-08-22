"""The frontend/backend contract.

`frontend/src/lib/types.ts` mirrors `backend/app/schemas.py` by hand, and the
frontend is a static export with no generated client, so nothing else would catch
a field added on one side and forgotten on the other. This reads the FastAPI
OpenAPI schema and fails naming the offending field.

Deliberately a text parse rather than a TypeScript compile: it needs no npm
install, so it runs in the same pytest pass as everything else. The tradeoff is
that it checks field presence and the shape of the type, not full assignability.
"""
import pathlib
import re

import pytest

from app.main import app

TYPES_TS = (
    pathlib.Path(__file__).resolve().parents[2] / "frontend" / "src" / "lib" / "types.ts"
)

# OpenAPI schema name -> TypeScript interface name. Equal today, but the mapping
# is explicit so a rename on either side is a visible edit here.
CHECKED = {
    "AskResponse": "AskResponse",
    "StageResult": "StageResult",
    "ContextResponse": "AppContext",
    "PolicyHit": "PolicyHit",
    "ReplayMeta": "ReplayMeta",
    "BulletinFacts": "BulletinFacts",
    "SectionText": "SectionText",
}


def parse_type_aliases(source: str) -> dict[str, str]:
    """Extract `export type Name = ...;` so a field typed by alias can be resolved."""
    return {
        m.group(1): m.group(2).strip()
        for m in re.finditer(r"export type (\w+)\s*=\s*([^;]+);", source, re.S)
    }


def parse_interfaces(source: str) -> dict[str, dict[str, str]]:
    """Extract `interface Name { field: type; }` blocks as {name: {field: type}}."""
    out: dict[str, dict[str, str]] = {}
    for match in re.finditer(r"export interface (\w+)\s*\{(.*?)\n\}", source, re.S):
        name, body = match.group(1), match.group(2)
        fields: dict[str, str] = {}
        for line in body.split("\n"):
            line = re.sub(r"//.*", "", line).strip().rstrip(";")
            field = re.match(r"(\w+)\??:\s*(.+)$", line)
            if field:
                fields[field.group(1)] = field.group(2).strip()
        out[name] = fields
    return out


def openapi_fields(schema_name: str) -> dict[str, dict]:
    schemas = app.openapi()["components"]["schemas"]
    assert schema_name in schemas, f"{schema_name} absent from the OpenAPI schema"
    return schemas[schema_name].get("properties", {})


@pytest.fixture(scope="module")
def source() -> str:
    assert TYPES_TS.is_file(), f"types.ts not found at {TYPES_TS}"
    return TYPES_TS.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def aliases(source) -> dict[str, str]:
    return parse_type_aliases(source)


@pytest.fixture(scope="module")
def interfaces(source) -> dict[str, dict[str, str]]:
    return parse_interfaces(source)


def _is_compatible(ts_type: str, spec: dict, aliases: dict[str, str]) -> bool:
    """Is the declared TypeScript type plausible for this OpenAPI property?

    Unwraps anyOf/nullable and checks the primitive kind. Deliberately lenient
    about object shapes — a nested interface is checked as its own entry.
    """
    # A field may be typed by alias (`stage: Stage`); compare what it resolves to.
    for name, definition in aliases.items():
        ts_type = re.sub(rf"\b{name}\b", definition, ts_type)

    variants = spec.get("anyOf") or [spec]
    kinds = {v.get("type") for v in variants if "type" in v}
    nullable = "null" in kinds
    kinds.discard("null")
    referenced = any("$ref" in v for v in variants)

    if nullable and "null" not in ts_type:
        return False
    if "array" in kinds and "[]" not in ts_type and "Array<" not in ts_type:
        return False
    if kinds == {"integer"} or kinds == {"number"}:
        return "number" in ts_type
    if kinds == {"boolean"}:
        return "boolean" in ts_type
    if kinds == {"string"}:
        # An enum maps to a union of string literals rather than `string`.
        if any("enum" in v for v in variants):
            return '"' in ts_type or "string" in ts_type
        return "string" in ts_type
    if referenced and not kinds:
        # A referenced model: expect a named interface, not a primitive.
        return not re.fullmatch(r"(string|number|boolean)(\s*\|\s*null)?", ts_type)
    return True


@pytest.mark.parametrize(("schema_name", "ts_name"), sorted(CHECKED.items()))
def test_every_backend_field_exists_in_types_ts(schema_name, ts_name, interfaces):
    assert ts_name in interfaces, f"types.ts declares no interface {ts_name}"
    declared = interfaces[ts_name]
    missing = sorted(set(openapi_fields(schema_name)) - set(declared))
    assert not missing, (
        f"{ts_name} in types.ts is missing {missing}, present on {schema_name} "
        f"in backend/app/schemas.py"
    )


@pytest.mark.parametrize(("schema_name", "ts_name"), sorted(CHECKED.items()))
def test_declared_types_are_compatible(schema_name, ts_name, interfaces, aliases):
    declared = interfaces[ts_name]
    incompatible = [
        f"{field}: OpenAPI {spec} vs types.ts {declared[field]!r}"
        for field, spec in openapi_fields(schema_name).items()
        if field in declared and not _is_compatible(declared[field], spec, aliases)
    ]
    assert not incompatible, f"{ts_name} type mismatch: {incompatible}"


@pytest.mark.parametrize(("schema_name", "ts_name"), sorted(CHECKED.items()))
def test_types_ts_declares_no_field_the_backend_does_not_send(
    schema_name, ts_name, interfaces
):
    """Drift runs both ways: a field the API never sends is equally misleading."""
    extra = sorted(set(interfaces[ts_name]) - set(openapi_fields(schema_name)))
    assert not extra, f"{ts_name} declares {extra}, absent from {schema_name}"


def test_the_parser_finds_the_interfaces_it_is_asked_about(interfaces, aliases):
    """Guard the guard: a parser returning nothing would make every test vacuous."""
    assert set(CHECKED.values()) <= set(interfaces)
    assert interfaces["PolicyHit"]["policy"] == "string"
    assert interfaces["StageResult"]["replayed"] == "ReplayMeta | null"
    assert "Stage" in aliases
