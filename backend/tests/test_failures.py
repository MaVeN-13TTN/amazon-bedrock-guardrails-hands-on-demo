"""Failure reporting.

A teaching artefact must never let a failure look like a result. These pin the
three ways a stage can fail and the fact that each reads differently from a
guardrail intervention — and from each other.
"""
import pytest
from botocore.exceptions import ClientError, ParamValidationError, ReadTimeoutError
from fastapi.testclient import TestClient

from app.config import Settings
from app.guardrails import GuardrailService
from app.main import app, get_service, get_settings
from tests.test_api import RecordingBedrock


class FailingBedrock(RecordingBedrock):
    """Raises a chosen exception from a chosen stage's call."""

    def __init__(self, exc: Exception, fail_on: str = "INPUT", **kw):
        super().__init__(**kw)
        self.exc = exc
        self.fail_on = fail_on

    def apply_guardrail(self, **kw):
        if self.fail_on == kw["source"]:
            self.calls.append(("apply_guardrail", kw["source"]))
            raise self.exc
        return super().apply_guardrail(**kw)

    def converse(self, **kw):
        if self.fail_on == "converse":
            self.calls.append(("converse", kw["modelId"]))
            raise self.exc
        return super().converse(**kw)


def client_with(stub, **overrides) -> TestClient:
    # answer_fallback off by default here: these tests assert that a model failure
    # surfaces as an error. The fallback path has its own tests below.
    overrides.setdefault("answer_fallback", False)
    cfg = Settings(guardrail_id="test-guardrail", guardrail_enabled=True, **overrides)
    app.dependency_overrides[get_settings] = lambda: cfg
    app.dependency_overrides[get_service] = lambda: GuardrailService(cfg, client=stub)
    return TestClient(app)


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


PARAM_ERROR = ParamValidationError(
    report='Unknown parameter in input: "outputScope", must be one of: guardrailIdentifier'
)


def test_a_rejected_parameter_names_the_parameter_and_the_stage():
    stub = FailingBedrock(PARAM_ERROR, fail_on="INPUT")
    r = client_with(stub).post("/api/ask", json={"input": "a question"})
    detail = r.json()["detail"]

    assert r.status_code == 400
    assert detail["kind"] == "parameter_validation"
    assert detail["stage"] == "screen"
    assert detail["parameter"] == "outputScope"


def test_a_rejected_parameter_stops_the_pipeline_immediately():
    """No further Bedrock call is made once a parameter is refused."""
    stub = FailingBedrock(PARAM_ERROR, fail_on="INPUT")
    client_with(stub).post("/api/ask", json={"input": "a question"})

    assert stub.converse_count == 0
    assert stub.verify_count == 0


def test_a_parameter_rejection_is_distinguishable_from_an_intervention():
    """An intervention is a 200 with stages; a rejection is a 400 with a kind."""
    rejected = client_with(FailingBedrock(PARAM_ERROR)).post(
        "/api/ask", json={"input": "a question"}
    )
    intervened = client_with(RecordingBedrock(screen_blocks=True)).post(
        "/api/ask", json={"input": "a question"}
    )

    assert rejected.status_code == 400
    assert "stages" not in rejected.json()
    assert intervened.status_code == 200
    assert intervened.json()["stopped_at"] == "screen"


def test_a_timeout_names_the_stage_and_elapsed_time_with_no_error_code():
    """No response arrived, so there is no AWS error code to assert."""
    stub = FailingBedrock(ReadTimeoutError(endpoint_url="https://bedrock"), fail_on="INPUT")
    r = client_with(stub).post("/api/ask", json={"input": "a question"})
    detail = r.json()["detail"]

    assert r.status_code == 504
    assert detail["kind"] == "timeout"
    assert detail["stage"] == "screen"
    assert isinstance(detail["elapsed_ms"], int)
    assert "aws_error_code" not in detail


def test_a_timeout_in_the_answer_stage_is_attributed_to_the_answer_stage():
    stub = FailingBedrock(ReadTimeoutError(endpoint_url="https://bedrock"), fail_on="converse")
    detail = client_with(stub).post("/api/ask", json={"input": "a question"}).json()["detail"]

    assert detail["stage"] == "answer"
    assert detail["kind"] == "timeout"


def test_an_aws_error_carries_its_code_and_the_failing_stage():
    error = ClientError(
        {"Error": {"Code": "ThrottlingException", "Message": "Too many requests"}},
        "ApplyGuardrail",
    )
    stub = FailingBedrock(error, fail_on="OUTPUT")
    r = client_with(stub).post("/api/ask", json={"input": "a question"})
    detail = r.json()["detail"]

    assert r.status_code == 502
    assert detail["kind"] == "aws_error"
    assert detail["stage"] == "verify"
    assert detail["aws_error_code"] == "ThrottlingException"
    assert "Too many requests" in detail["detail"]


def test_access_denied_still_returns_403_with_the_stage_named():
    """The most common live-demo failure: model access not enabled."""
    error = ClientError(
        {"Error": {"Code": "AccessDeniedException", "Message": "no model access"}},
        "Converse",
    )
    stub = FailingBedrock(error, fail_on="converse")
    r = client_with(stub).post("/api/ask", json={"input": "a question"})

    assert r.status_code == 403
    assert r.json()["detail"]["stage"] == "answer"
    assert r.json()["detail"]["aws_error_code"] == "AccessDeniedException"


def test_a_missing_guardrail_is_still_a_plain_503_string():
    """Configuration is not a stage failure, so it keeps its readable message."""
    cfg = Settings(guardrail_id="")
    app.dependency_overrides[get_settings] = lambda: cfg
    app.dependency_overrides[get_service] = lambda: GuardrailService(
        cfg, client=RecordingBedrock()
    )
    r = TestClient(app).post("/api/ask", json={"input": "a question"})

    assert r.status_code == 503
    assert "No guardrail configured" in r.json()["detail"]


def test_verify_endpoint_failures_are_also_attributed():
    stub = FailingBedrock(ReadTimeoutError(endpoint_url="https://bedrock"), fail_on="OUTPUT")
    r = client_with(stub).post(
        "/api/verify", json={"question": "when?", "answer": "at 06:00"}
    )

    assert r.status_code == 504
    assert r.json()["detail"]["stage"] == "verify"


def test_a_model_failure_falls_back_to_a_canned_answer():
    """An SCP or absent model access must not cost the guardrail stages.

    Stages 1 and 3 need no model, so the pipeline still runs them live and stage 2
    substitutes a bulletin-grounded answer, labelled as a fallback.
    """
    error = ClientError(
        {"Error": {"Code": "AccessDeniedException", "Message": "explicit deny in an SCP"}},
        "Converse",
    )
    stub = FailingBedrock(error, fail_on="converse")
    body = client_with(stub, answer_fallback=True).post(
        "/api/ask", json={"input": "When are the collection points open?"}
    ).json()

    assert [s["stage"] for s in body["stages"]] == ["screen", "answer", "verify"]
    assert body["stopped_at"] is None
    # Nothing claims a model ran.
    assert [s["model_invoked"] for s in body["stages"]] == [False, False, False]
    answer = next(s for s in body["stages"] if s["stage"] == "answer")
    assert answer["stop_reason"] == "fallback_no_model"
    assert answer["replayed"] is not None
    # The answer is drawn from the bulletin, so verify has something grounded.
    assert "06:00" in body["final"]


def test_the_fallback_answer_matches_the_question_asked():
    error = ClientError({"Error": {"Code": "AccessDeniedException"}}, "Converse")
    stub = FailingBedrock(error, fail_on="converse")
    body = client_with(stub, answer_fallback=True).post(
        "/api/ask", json={"input": "How long after grading do I get paid?"}
    ).json()
    assert "fourteen days" in body["final"]


def test_a_guardrail_failure_still_errors_even_with_fallback_on():
    """The fallback covers the model only. A guardrail failure must surface."""
    error = ClientError({"Error": {"Code": "AccessDeniedException"}}, "ApplyGuardrail")
    stub = FailingBedrock(error, fail_on="INPUT")
    r = client_with(stub, answer_fallback=True).post("/api/ask", json={"input": "a question"})

    assert r.status_code == 403
    assert r.json()["detail"]["stage"] == "screen"
