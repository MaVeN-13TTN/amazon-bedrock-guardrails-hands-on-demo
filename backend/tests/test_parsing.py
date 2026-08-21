"""Assessment parsing.

The two Bedrock APIs report differently and both shapes must be handled, so
these fixtures are the regression net for the trickiest code in the backend.
"""
from app.guardrails import parse_assessments, parse_trace

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
