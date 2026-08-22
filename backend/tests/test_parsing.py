"""Assessment parsing.

The two Bedrock APIs report differently and both shapes must be handled, so
these fixtures are the regression net for the trickiest code in the backend.
"""
from app.guardrails import _strip, parse_assessments, parse_trace

GID = "abcd1234efgh"

# apply_guardrail returns a flat `assessments` list, not keyed by guardrail id.
APPLY_GUARDRAIL_ASSESSMENTS = [
    {
        "topicPolicy": {"topics": [
            {"name": "Agrochemical Dosing", "type": "DENY", "action": "BLOCKED"},
        ]},
        "contentPolicy": {"filters": [
            {"type": "PROMPT_ATTACK", "confidence": "HIGH", "action": "BLOCKED"},
            {"type": "HATE", "confidence": "NONE", "action": "NONE"},
        ]},
        "wordPolicy": {
            "customWords": [{"match": "Project Tumaini", "action": "BLOCKED"}],
            "managedWordLists": [{"match": "***", "type": "PROFANITY", "action": "BLOCKED"}],
        },
        "sensitiveInformationPolicy": {
            "piiEntities": [
                {"type": "NAME", "match": "Grace Wanjiku", "action": "ANONYMIZED"},
                {"type": "PHONE", "match": "0722135790", "action": "ANONYMIZED"},
            ],
            "regexes": [
                {"name": "Co-op Member Number", "match": "HG-004182", "action": "ANONYMIZED"},
            ],
        },
        "contextualGroundingPolicy": {"filters": [
            {"type": "GROUNDING", "threshold": 0.7, "score": 0.31, "action": "BLOCKED"},
            {"type": "RELEVANCE", "threshold": 0.7, "score": 0.95, "action": "NONE"},
        ]},
    }
]


def test_apply_guardrail_shape_parses_every_policy():
    hits = parse_assessments(APPLY_GUARDRAIL_ASSESSMENTS, "input")
    policies = [h.policy for h in hits]
    assert "denied topic" in policies
    assert "content filter" in policies
    assert "word filter" in policies
    assert "managed word list" in policies
    assert "PII" in policies
    assert "PII regex" in policies
    assert "grounding" in policies
    assert "relevance" in policies
    assert len(hits) == 9


def test_none_actions_are_dropped():
    """A filter that considered the text and passed is not a finding."""
    hits = parse_assessments(APPLY_GUARDRAIL_ASSESSMENTS, "input")
    assert not [h for h in hits if h.policy == "content filter" and h.action == "NONE"]
    assert not [h for h in hits if h.detail == "HATE"]


def test_grounding_and_relevance_carry_scores_independently():
    hits = parse_assessments(APPLY_GUARDRAIL_ASSESSMENTS, "output")
    grounding = next(h for h in hits if h.policy == "grounding")
    relevance = next(h for h in hits if h.policy == "relevance")
    assert grounding.score == 0.31 and grounding.threshold == 0.7
    assert grounding.passed is False
    # Relevance passing while grounding fails is the whole point of two checks.
    assert relevance.passed is True


def test_converse_trace_handles_dict_and_list_shapes():
    """inputAssessment maps id -> assessment; outputAssessments maps id -> [assessment]."""
    trace = {"guardrail": {
        "inputAssessment": {GID: {
            "topicPolicy": {"topics": [{"name": "Credit Terms", "action": "BLOCKED"}]}
        }},
        "outputAssessments": {GID: [{
            "contentPolicy": {"filters": [
                {"type": "VIOLENCE", "confidence": "MEDIUM", "action": "BLOCKED"}
            ]}
        }]},
    }}
    hits = parse_trace(trace)
    assert len(hits) == 2
    assert {h.where for h in hits} == {"input", "output"}
    assert next(h for h in hits if h.where == "input").detail == "Credit Terms"
    assert next(h for h in hits if h.where == "output").detail == "VIOLENCE"


def test_empty_and_missing_traces_are_safe():
    assert parse_trace(None) == []
    assert parse_trace({}) == []
    assert parse_trace({"guardrail": {}}) == []
    assert parse_assessments(None, "input") == []


def test_empty_assessments_list_is_safe():
    """An empty list is different from None, and both mean no findings."""
    assert parse_assessments([], "input") == []
    assert parse_assessments([{}], "input") == []


def test_a_missing_policy_section_does_not_raise():
    """A response carrying only one policy must parse, not error on the rest."""
    hits = parse_assessments(
        [{"topicPolicy": {"topics": [{"name": "Credit Terms", "action": "BLOCKED"}]}}],
        "input",
    )
    assert [h.detail for h in hits] == ["Credit Terms"]


def test_input_assessment_maps_to_one_object_not_a_list():
    """converse puts inputAssessment as id -> assessment, singular."""
    trace = {"guardrail": {"inputAssessment": {GID: {
        "topicPolicy": {"topics": [{"name": "Land Tenure Disputes", "action": "BLOCKED"}]},
    }}}}
    hits = parse_trace(trace)
    assert [(h.detail, h.where) for h in hits] == [("Land Tenure Disputes", "input")]


def test_output_assessments_maps_to_a_list_parsed_in_order():
    """outputAssessments is id -> [assessment]; every element counts, in order."""
    trace = {"guardrail": {"outputAssessments": {GID: [
        {"contentPolicy": {"filters": [{"type": "HATE", "action": "BLOCKED"}]}},
        {"contentPolicy": {"filters": [{"type": "VIOLENCE", "action": "BLOCKED"}]}},
    ]}}}
    hits = parse_trace(trace)
    assert [h.detail for h in hits] == ["HATE", "VIOLENCE"]
    assert {h.where for h in hits} == {"output"}


def test_a_flat_assessment_and_the_same_one_in_a_trace_agree():
    """The two API shapes must not produce different findings for one policy."""
    assessment = {
        "wordPolicy": {"customWords": [{"match": "Project Tumaini", "action": "BLOCKED"}]},
    }
    flat = parse_assessments([assessment], "input")
    wrapped = parse_trace({"guardrail": {"inputAssessment": {GID: assessment}}})
    assert [h.model_dump() for h in flat] == [h.model_dump() for h in wrapped]


def test_word_and_pii_findings_survive_a_none_action():
    """A rule that matched is reported whatever was done about it.

    Content filters and denied topics are the opposite: there, NONE means the
    policy looked and let it through, which is not a finding.
    """
    hits = parse_assessments([{
        "wordPolicy": {
            "customWords": [{"match": "Batch Ledger v2", "action": "NONE"}],
            "managedWordLists": [{"type": "PROFANITY", "action": "NONE"}],
        },
        "sensitiveInformationPolicy": {
            "piiEntities": [{"type": "NAME", "action": "NONE"}],
            "regexes": [{"name": "National ID", "action": "NONE"}],
        },
        "contentPolicy": {"filters": [{"type": "HATE", "action": "NONE"}]},
        "topicPolicy": {"topics": [{"name": "Credit Terms", "action": "NONE"}]},
    }], "input")
    assert [h.policy for h in hits] == [
        "word filter", "managed word list", "PII", "PII regex",
    ]


def test_grounding_hits_are_emitted_even_when_passing():
    """outputScope=FULL returns passing checks, and the score is the lesson."""
    hits = parse_assessments([{"contextualGroundingPolicy": {"filters": [
        {"type": "GROUNDING", "threshold": 0.7, "score": 0.92, "action": "NONE"},
        {"type": "RELEVANCE", "threshold": 0.7, "score": 0.88, "action": "NONE"},
    ]}}], "output")
    assert [h.policy for h in hits] == ["grounding", "relevance"]
    assert all(h.passed for h in hits)
    assert hits[0].score == 0.92 and hits[0].threshold == 0.7


def test_hits_come_out_in_declared_section_order_whatever_the_key_order():
    """The UI renders these in sequence, so the order cannot follow dict order."""
    sections = {
        "contextualGroundingPolicy": {"filters": [
            {"type": "GROUNDING", "threshold": 0.7, "score": 0.4, "action": "BLOCKED"}]},
        "sensitiveInformationPolicy": {"piiEntities": [
            {"type": "PHONE", "action": "ANONYMIZED"}]},
        "topicPolicy": {"topics": [{"name": "Credit Terms", "action": "BLOCKED"}]},
        "contentPolicy": {"filters": [{"type": "HATE", "action": "BLOCKED"}]},
        "wordPolicy": {"customWords": [{"match": "Project Tumaini", "action": "BLOCKED"}]},
    }
    expected = ["content filter", "denied topic", "word filter", "PII", "grounding"]
    assert [h.policy for h in parse_assessments([sections], "input")] == expected
    # Same content, keys reversed: the emitted order must not move.
    reversed_keys = dict(reversed(list(sections.items())))
    assert [h.policy for h in parse_assessments([reversed_keys], "input")] == expected


def test_strip_removes_response_metadata_and_keeps_everything_else():
    payload = {
        "ResponseMetadata": {"RequestId": "abc", "HTTPStatusCode": 200},
        "action": "GUARDRAIL_INTERVENED",
        "assessments": [{"topicPolicy": {}}],
        "usage": {"topicPolicyUnits": 1},
    }
    stripped = _strip(payload)
    assert "ResponseMetadata" not in stripped
    assert stripped == {k: v for k, v in payload.items() if k != "ResponseMetadata"}


def test_strip_passes_through_a_non_dict():
    assert _strip(None) is None
    assert _strip([1, 2]) == [1, 2]
