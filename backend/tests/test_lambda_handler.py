"""The Lambda entry point, exercised without AWS.

`backend/lambda_handler.py` is ten lines of glue, and until now it was the only
module in the repository that nothing executed. It could not be: the deployed
stack has never been stood up, because `iam:CreateRole` is denied in the account
this project was built in (validation log V-29). So the first person to run this
code would have been an attendee following RUNNING.md Path A.

Mangum's contract does not need AWS. It translates an API Gateway HTTP API
payload-format-2.0 event into an ASGI call and translates the response back, so a
synthetic event exercises the whole path — routing, the JSON body, status codes
and headers — under Replay_Mode, with no credentials present.

What this does **not** prove: IAM, networking, the bundle's architecture, or that
API Gateway constructs the event the way this file assumes. Those need a real
deployment. It proves the handler is wired up and answers.
"""
from __future__ import annotations

import json
import pathlib

import pytest

FIXTURES = pathlib.Path(__file__).resolve().parents[1] / "app" / "fixtures" / "replay"


@pytest.fixture
def handler(monkeypatch):
    """Import the handler with Replay_Mode on, as a no-credentials environment."""
    for var in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN",
                "AWS_PROFILE", "AWS_DEFAULT_REGION", "AWS_REGION"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("REPLAY_MODE", "true")
    monkeypatch.setenv("REPLAY_DIR", str(FIXTURES))
    monkeypatch.setenv("GUARDRAIL_ENABLED", "true")
    # Set explicitly rather than inherited. Terraform sets GUARDRAIL_ID on the
    # deployed function, so this mirrors it — and without it the test passes or
    # fails depending on whether the developer happens to have a `backend/.env`,
    # which is how this test first went green for the wrong reason.
    monkeypatch.setenv("GUARDRAIL_ID", "test-guardrail-id")
    monkeypatch.setenv("GUARDRAIL_VERSION", "DRAFT")

    import app.config
    import app.main
    import lambda_handler

    app.config.get_settings.cache_clear()
    app.main.get_service.cache_clear()
    return lambda_handler.handler


def _event(method: str, path: str, body: dict | None = None) -> dict:
    """An API Gateway HTTP API payload format 2.0 event."""
    return {
        "version": "2.0",
        "routeKey": f"{method} {path}",
        "rawPath": path,
        "rawQueryString": "",
        "headers": {
            "content-type": "application/json",
            "host": "example.execute-api.eu-west-1.amazonaws.com",
        },
        "requestContext": {
            "http": {
                "method": method,
                "path": path,
                "protocol": "HTTP/1.1",
                "sourceIp": "203.0.113.1",
            },
            "stage": "$default",
            "requestId": "test-request",
            "apiId": "example",
            "domainName": "example.execute-api.eu-west-1.amazonaws.com",
        },
        "body": json.dumps(body) if body is not None else None,
        "isBase64Encoded": False,
    }


class _Context:
    function_name = "kilimo-desk-api"
    memory_limit_in_mb = 512
    invoked_function_arn = "arn:aws:lambda:eu-west-1:111122223333:function:kilimo-desk-api"
    aws_request_id = "test-request"

    def get_remaining_time_in_millis(self) -> int:
        return 60_000


def test_the_handler_answers_a_health_check(handler):
    response = handler(_event("GET", "/health"), _Context())

    assert response["statusCode"] == 200
    assert json.loads(response["body"])["status"] == "ok"


def test_the_handler_runs_the_whole_pipeline(handler):
    """A recorded in-scope prompt, through Mangum, with no credentials."""
    event = _event("POST", "/api/ask", {"input": "When are the collection points open?"})
    response = handler(event, _Context())

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert [s["stage"] for s in body["stages"]] == ["screen", "answer", "verify"]
    assert body["stopped_at"] is None


def test_the_handler_reports_a_validation_error_rather_than_a_stack_trace(handler):
    response = handler(_event("POST", "/api/ask", {"input": ""}), _Context())

    assert response["statusCode"] == 422
    assert "Traceback" not in response["body"]


def test_the_handler_returns_a_json_content_type(handler):
    response = handler(_event("GET", "/health"), _Context())
    headers = {k.lower(): v for k, v in response.get("headers", {}).items()}

    assert "application/json" in headers.get("content-type", "")
