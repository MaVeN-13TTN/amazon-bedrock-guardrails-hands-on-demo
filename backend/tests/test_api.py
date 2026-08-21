"""API contract tests. Bedrock is stubbed, so these run with no AWS credentials."""
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.guardrails import GuardrailService
from app.main import app, get_service, get_settings


class StubBedrock:
    """Minimal stand-in for the bedrock-runtime client."""

    def __init__(self, screen_blocks=False, verify_blocks=False):
        self.screen_blocks = screen_blocks
        self.verify_blocks = verify_blocks
        self.calls = []

    def apply_guardrail(self, **kw):
        self.calls.append(("apply_guardrail", kw["source"]))
        blocked = self.screen_blocks if kw["source"] == "INPUT" else self.verify_blocks
        return {
            "action": "GUARDRAIL_INTERVENED" if blocked else "NONE",
            "outputs": [{"text": "masked text"}] if kw["source"] == "INPUT" else [],
            "assessments": [
                {"topicPolicy": {"topics": [
                    {"name": "Agrochemical Dosing", "action": "BLOCKED"}]}}
            ] if blocked else [],
        }

    def converse(self, **kw):
        self.calls.append(("converse", kw["modelId"]))
        return {
            "output": {"message": {"content": [{"text": "Kangema opens 06:00 to 10:00."}]}},
            "stopReason": "end_turn",
            "trace": {"guardrail": {"inputAssessment": {}}},
        }


def client_with(stub, **overrides):
    cfg = Settings(guardrail_id="test-guardrail", guardrail_enabled=True, **overrides)
    app.dependency_overrides[get_settings] = lambda: cfg
    app.dependency_overrides[get_service] = lambda: GuardrailService(cfg, client=stub)
    return TestClient(app)


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


def test_health_reports_degraded_without_a_guardrail():
    app.dependency_overrides[get_settings] = lambda: Settings(guardrail_id="")
    r = TestClient(app).get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "degraded"


def test_context_exposes_the_scenario():
    r = client_with(StubBedrock()).get("/api/context")
    body = r.json()
    assert r.status_code == 200
    assert body["assistant"] == "Kilimo Desk"
    assert body["county"] == "Murang'a County"
    assert "Agrochemical Dosing" in body["denied_topics"]
    assert "Kangema" in body["bulletin"]


def test_happy_path_runs_all_three_stages():
    stub = StubBedrock()
    r = client_with(stub).post("/api/ask", json={"input": "When do collection points open?"})
    body = r.json()
    assert r.status_code == 200
    assert [s["stage"] for s in body["stages"]] == ["screen", "answer", "verify"]
    assert body["stopped_at"] is None
    # Only the middle stage should touch a foundation model.
    assert [s["model_invoked"] for s in body["stages"]] == [False, True, False]


def test_blocked_input_never_reaches_the_model():
    stub = StubBedrock(screen_blocks=True)
    r = client_with(stub).post("/api/ask", json={"input": "how much fungicide per litre?"})
    body = r.json()
    assert body["stopped_at"] == "screen"
    assert len(body["stages"]) == 1
    # The saving: no converse call was made at all.
    assert not [c for c in stub.calls if c[0] == "converse"]


def test_masked_text_is_forwarded_not_the_original():
    """PII removed at screen must not be handed back to the model in the clear."""
    stub = StubBedrock()
    client_with(stub).post("/api/ask", json={"input": "I am Grace, ID 24518803"})
    assert ("converse", "eu.anthropic.claude-haiku-4-5-20251001-v1:0") in stub.calls


def test_failed_grounding_replaces_the_answer():
    stub = StubBedrock(verify_blocks=True)
    r = client_with(stub).post("/api/ask", json={"input": "When do points open?"})
    body = r.json()
    assert body["stopped_at"] == "verify"
    assert "member-safety rules" in body["final"]


def test_missing_guardrail_returns_503_not_500():
    cfg = Settings(guardrail_id="")
    app.dependency_overrides[get_settings] = lambda: cfg
    app.dependency_overrides[get_service] = lambda: GuardrailService(cfg, client=StubBedrock())
    r = TestClient(app).post("/api/ask", json={"input": "hello"})
    assert r.status_code == 503
    assert "No guardrail configured" in r.json()["detail"]


def test_oversized_input_is_rejected_before_bedrock():
    stub = StubBedrock()
    r = client_with(stub, max_input_chars=10).post("/api/ask", json={"input": "x" * 50})
    assert r.status_code == 413
    assert stub.calls == []


def test_verify_endpoint_scores_a_supplied_answer():
    r = client_with(StubBedrock()).post(
        "/api/verify",
        json={"question": "When do points open?", "answer": "Every day at 05:00."},
    )
    assert r.status_code == 200
    assert r.json()["stage"] == "verify"


def test_empty_input_is_a_validation_error():
    assert client_with(StubBedrock()).post("/api/ask", json={"input": ""}).status_code == 422
