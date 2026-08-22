"""Parser properties, stated as properties.

`test_parsing.py` pins the real Bedrock response shapes by example, which
generated data cannot do. These tests cover the claims that have to hold for
*every* assessment — that the hit count matches the findings, that the two API
shapes agree, and that repetition composes — because the UI panels are built
entirely from this output and a silent miscount would misinform an audience.
"""
from hypothesis import given, settings
from hypothesis import strategies as st

from app.guardrails import _DROP_NONE_ACTION, _SECTIONS, parse_assessments, parse_trace

GID = "abcd1234efgh"

_ACTIONS = st.sampled_from(["BLOCKED", "ANONYMIZED", "NONE"])

# One strategy per section, keyed by the (policy, items) pair that identifies it,
# so the generated shape always matches what the parser looks for.
_ITEM_STRATEGIES = {
    ("contentPolicy", "filters"): st.fixed_dictionaries({
        "type": st.sampled_from(["HATE", "INSULTS", "VIOLENCE", "PROMPT_ATTACK"]),
        "confidence": st.sampled_from(["HIGH", "MEDIUM", "LOW", "NONE"]),
        "action": _ACTIONS,
    }),
    ("topicPolicy", "topics"): st.fixed_dictionaries({
        "name": st.sampled_from(["Agrochemical Dosing", "Credit Terms"]),
        "action": _ACTIONS,
    }),
    ("wordPolicy", "customWords"): st.fixed_dictionaries({
        "match": st.sampled_from(["Project Tumaini", "Batch Ledger v2"]),
        "action": _ACTIONS,
    }),
    ("wordPolicy", "managedWordLists"): st.fixed_dictionaries({
        "type": st.just("PROFANITY"), "action": _ACTIONS,
    }),
    ("sensitiveInformationPolicy", "piiEntities"): st.fixed_dictionaries({
        "type": st.sampled_from(["NAME", "PHONE"]), "action": _ACTIONS,
    }),
    ("sensitiveInformationPolicy", "regexes"): st.fixed_dictionaries({
        "name": st.sampled_from(["Co-op Member Number", "National ID"]),
        "action": _ACTIONS,
    }),
    ("contextualGroundingPolicy", "filters"): st.fixed_dictionaries({
        "type": st.sampled_from(["GROUNDING", "RELEVANCE"]),
        "threshold": st.just(0.7),
        "score": st.floats(0, 1, allow_nan=False),
        "action": _ACTIONS,
    }),
}


@st.composite
def assessments(draw, shuffle_keys: bool = True) -> dict:
    """An assessment carrying any subset of the seven sections, in any key order."""
    chosen = draw(st.lists(st.sampled_from(sorted(_ITEM_STRATEGIES)),
                           unique=True, min_size=0, max_size=7))
    built: dict[str, dict] = {}
    for policy, items in chosen:
        entries = draw(st.lists(_ITEM_STRATEGIES[(policy, items)], min_size=0, max_size=3))
        built.setdefault(policy, {})[items] = entries
    if shuffle_keys and built:
        order = draw(st.permutations(sorted(built)))
        built = {k: built[k] for k in order}
    return built


def qualifying_count(assessment: dict) -> int:
    """Count findings the parser should emit, derived from the rules, not the code."""
    total = 0
    for section in _SECTIONS:
        for item in (assessment.get(section.policy) or {}).get(section.items) or []:
            if section.policy in _DROP_NONE_ACTION and item.get("action") == "NONE":
                continue
            total += 1
    return total


@given(assessments())
def test_hit_count_equals_the_qualifying_finding_count(assessment):
    hits = parse_assessments([assessment], "input")
    assert len(hits) == qualifying_count(assessment)


@given(assessments())
def test_section_order_is_stable_under_key_reordering(assessment):
    """The UI renders hits in sequence, so emission order cannot follow dict order."""
    forward = [h.policy for h in parse_assessments([assessment], "input")]
    reordered = dict(reversed(list(assessment.items())))
    assert [h.policy for h in parse_assessments([reordered], "input")] == forward


@given(assessments())
def test_flat_and_trace_wrapped_parses_agree_field_by_field(assessment):
    """Metamorphic: the response shape must not change what was found.

    Only `where` may differ, and here both are input, so even that must match.
    """
    flat = parse_assessments([assessment], "input")
    wrapped = parse_trace({"guardrail": {"inputAssessment": {GID: assessment}}})
    assert len(flat) == len(wrapped)
    for a, b in zip(flat, wrapped, strict=True):
        assert a.model_dump() == b.model_dump()


@given(assessments())
def test_the_shape_determines_only_the_location_field(assessment):
    """Wrapped as an output assessment, hits are identical but for `where`."""
    flat = parse_assessments([assessment], "output")
    wrapped = parse_trace({"guardrail": {"outputAssessments": {GID: [assessment]}}})
    assert [h.model_dump() for h in flat] == [h.model_dump() for h in wrapped]
    assert all(h.where == "output" for h in wrapped)


@given(assessments(), st.integers(min_value=1, max_value=10))
@settings(max_examples=50)
def test_n_identical_copies_yield_n_repetitions(assessment, n):
    """Metamorphic: outputAssessments holding N copies repeats the sequence N times."""
    single = parse_trace({"guardrail": {"outputAssessments": {GID: [assessment]}}})
    many = parse_trace({"guardrail": {"outputAssessments": {GID: [assessment] * n}}})
    assert len(many) == len(single) * n
    assert [h.model_dump() for h in many] == [h.model_dump() for h in single] * n


@given(st.lists(assessments(), min_size=0, max_size=5))
def test_a_list_of_assessments_concatenates_their_hits(many):
    """0 to 50 assessments in a flat list: hits accumulate, none are lost."""
    assert len(parse_assessments(many, "input")) == sum(qualifying_count(a) for a in many)


@given(assessments())
def test_every_hit_carries_the_location_the_caller_stated(assessment):
    for where in ("input", "output"):
        assert all(h.where == where for h in parse_assessments([assessment], where))


@given(assessments())
def test_grounding_passed_is_true_exactly_when_the_action_is_none(assessment):
    for hit in parse_assessments([assessment], "output"):
        if hit.policy in ("grounding", "relevance"):
            assert hit.passed is (hit.action == "NONE")
        else:
            assert hit.passed is None
