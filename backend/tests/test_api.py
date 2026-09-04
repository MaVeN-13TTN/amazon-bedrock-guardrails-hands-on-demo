"""API contract tests. Bedrock is stubbed, so these run with no AWS credentials."""
import pytest
from fastapi.testclient import TestClient

from app import scenario
from app.config import Settings
from app.guardrails import GuardrailService
from app.main import app, get_service, get_settings


class RecordingBedrock:
    """Stand-in for the bedrock-runtime client that records complete requests.

    Recording every keyword argument, not just the call name, is the point: the
    masking claim is that the *rewritten* text reaches the model, and a stub that
    only remembers the model id cannot tell the difference.
    """

    def __init__(
        self,
        screen_blocks=False,
        answer_blocks=False,
        verify_blocks=False,
        masked_text="masked text",
    ):
        self.screen_blocks = screen_blocks
        self.answer_blocks = answer_blocks
        self.verify_blocks = verify_blocks
        self.masked_text = masked_text
        self.calls: list[tuple[str, str]] = []
        self.apply_requests: list[dict] = []
        self.converse_requests: list[dict] = []

    # --- recorded call sites ------------------------------------------------

    def apply_guardrail(self, **kw):
        self.calls.append(("apply_guardrail", kw["source"]))
        self.apply_requests.append(kw)
        blocked = self.screen_blocks if kw["source"] == "INPUT" else self.verify_blocks
        return {
            "action": "GUARDRAIL_INTERVENED" if blocked else "NONE",
            "outputs": [{"text": self.masked_text}] if kw["source"] == "INPUT" else [],
            "assessments": [
                {"topicPolicy": {"topics": [
                    {"name": "Agrochemical Dosing", "action": "BLOCKED"}]}}
            ] if blocked else [],
        }

    def converse(self, **kw):
        self.calls.append(("converse", kw["modelId"]))
        self.converse_requests.append(kw)
        if self.answer_blocks:
            return {
                "output": {"message": {"content": [{"text": "blocked by policy"}]}},
                "stopReason": "guardrail_intervened",
                "trace": {"guardrail": {"outputAssessments": {"g1": [
                    {"contentPolicy": {"filters": [
                        {"type": "VIOLENCE", "action": "BLOCKED"}]}}
                ]}}},
            }
        return {
            "output": {"message": {"content": [{"text": "Kangema opens 06:00 to 10:00."}]}},
            "stopReason": "end_turn",
            "trace": {"guardrail": {"inputAssessment": {}}},
        }

    # --- convenience for assertions ----------------------------------------

    @property
    def converse_count(self) -> int:
        return len(self.converse_requests)

    @property
    def verify_count(self) -> int:
        return len([r for r in self.apply_requests if r["source"] == "OUTPUT"])

    def guard_text(self, index: int = 0) -> str:
        """The text inside guardContent of a recorded Converse request."""
        content = self.converse_requests[index]["messages"][0]["content"][0]
        return content["guardContent"]["text"]["text"]

    def all_converse_text(self, index: int = 0) -> str:
        """Every text field of a recorded Converse request, concatenated."""
        import json

        return json.dumps(self.converse_requests[index])


# Retained so the existing tests read unchanged; the recording stub is a superset.
StubBedrock = RecordingBedrock


def client_with(stub, **overrides):
    cfg = Settings(guardrail_id="test-guardrail", guardrail_enabled=True, **overrides)
    app.dependency_overrides[get_settings] = lambda: cfg
    app.dependency_overrides[get_service] = lambda: GuardrailService(cfg, client=stub)
    return TestClient(app)


@pytest.fixture
def client():
    """A client over a stub that behaves like a healthy guardrail."""
    return client_with(RecordingBedrock())


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


def test_context_carries_the_landing_page_content():
    """The Landing_Page holds no scenario text of its own, so it all arrives here."""
    body = client_with(StubBedrock()).get("/api/context").json()
    facts = body["bulletin_facts"]
    assert facts["collection_points"] == ["Kangema", "Kiriaini"]
    assert facts["collection_opens"] == "06:00"
    assert facts["collection_closes"] == "10:00"
    assert facts["collection_days"] == ["Tuesday", "Friday"]
    assert facts["payment_delay_days"] == 14
    assert "member number" in facts["gate_requirement"]
    # 4 titled sections total: 2 here, plus collection and payment from the facts.
    assert [s["title"] for s in body["about_sections"]] == [
        "Who we are",
        "What we do for members",
    ]


def test_context_landing_facts_appear_in_the_bulletin_it_returns():
    """A member could check the page against the bulletin; both come from here."""
    body = client_with(StubBedrock()).get("/api/context").json()
    bulletin = body["bulletin"]
    facts = body["bulletin_facts"]
    for point in facts["collection_points"]:
        assert point in bulletin
    assert facts["gate_requirement"] in bulletin
    assert facts["payment_note"] in bulletin


def test_stage_results_are_not_marked_replayed_on_a_live_call():
    """`replayed` is provenance: absent unless a fixture served the stage."""
    body = client_with(StubBedrock()).post(
        "/api/ask", json={"input": "When do collection points open?"}
    ).json()
    assert [s["replayed"] for s in body["stages"]] == [None, None, None]


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
    """PII removed at screen must not be handed back to the model in the clear.

    The old version of this test asserted only that converse was called with the
    expected model id, which would have passed even if the unmasked text were
    forwarded — the one test in the suite that did not test its own name.
    """
    stub = RecordingBedrock(masked_text="I am {NAME}, ID {NATIONAL_ID}")
    client_with(stub).post("/api/ask", json={"input": "I am Grace, ID 24518803"})

    assert stub.converse_count == 1
    # Character for character, the rewritten text is what the model receives.
    assert stub.guard_text() == "I am {NAME}, ID {NATIONAL_ID}"
    # And the original values are nowhere in the request at all.
    sent = stub.all_converse_text()
    assert "Grace" not in sent
    assert "24518803" not in sent


def test_every_top_level_converse_parameter_is_asserted():
    """A stub recording only the model id must not be able to satisfy this."""
    stub = RecordingBedrock()
    client_with(stub).post("/api/ask", json={"input": "When do points open?"})
    request = stub.converse_requests[0]

    assert set(request) == {"modelId", "system", "messages", "inferenceConfig", "guardrailConfig"}
    assert request["modelId"] == "global.anthropic.claude-haiku-4-5-20251001-v1:0"
    assert request["system"] == [{"text": scenario.SYSTEM_PROMPT}]
    assert request["inferenceConfig"] == {"maxTokens": 400, "temperature": 0.2}
    assert request["guardrailConfig"] == {
        "guardrailIdentifier": "test-guardrail",
        "guardrailVersion": "DRAFT",
        # Without trace enabled you learn that a request was blocked, never which
        # policy blocked it, and every panel in the UI is built from the trace.
        "trace": "enabled",
    }
    # The user text is wrapped so only that span is evaluated: the system prompt's
    # own boundary rules must not trip the filters.
    assert request["messages"] == [
        {"role": "user", "content": [
            {"guardContent": {"text": {"text": "masked text"}}}]}
    ]


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


def test_input_over_2000_chars_is_rejected_with_zero_bedrock_calls():
    """The schema limit, Settings.max_input_chars and the Chat_Window all say 2000."""
    stub = StubBedrock()
    r = client_with(stub).post("/api/ask", json={"input": "x" * 2001})
    assert r.status_code == 422
    assert stub.calls == []
    # The error has to name the limit, or a caller cannot tell what to fix.
    assert "2000" in r.text


def test_input_of_exactly_2000_chars_is_accepted():
    """The boundary is inclusive: 2000 passes, 2001 does not."""
    stub = StubBedrock()
    r = client_with(stub).post("/api/ask", json={"input": "x" * 2000})
    assert r.status_code == 200
    assert [c[0] for c in stub.calls][0] == "apply_guardrail"


def test_verify_endpoint_scores_a_supplied_answer():
    r = client_with(StubBedrock()).post(
        "/api/verify",
        json={"question": "When do points open?", "answer": "Every day at 05:00."},
    )
    assert r.status_code == 200
    assert r.json()["stage"] == "verify"


def test_empty_input_is_a_validation_error():
    assert client_with(StubBedrock()).post("/api/ask", json={"input": ""}).status_code == 422


# --- SDK diagnostics ---------------------------------------------------------


def test_the_sdk_diagnostics_endpoint_reports_both_field_directions(client):
    """R11.1 — it must answer for a request field and a response field separately.

    The two fail in opposite ways: a rejected request field raises
    (V-14); a dropped response field is silently absent (V-24).
    """
    body = client.get("/api/diagnostics/sdk").json()
    assert body["outputScope_in_service_model"] is True
    assert body["tier_in_service_model"] is True


def test_the_sdk_diagnostics_endpoint_probes_both_call_sites(client):
    """Screen and verify both pass outputScope, so both are probed."""
    probes = client.get("/api/diagnostics/sdk").json()["probes"]
    assert set(probes) == {"screen", "verify"}
    for site, probe in probes.items():
        assert probe["accepted"] is True, site
        assert probe["rejection"] is None, site
        assert probe["outputScope"] == "FULL"


def test_the_sdk_diagnostics_endpoint_counts_none_action_assessments(client):
    """outputScope=FULL's purpose: policies that evaluated the text and allowed it.

    A count of zero means the parameter was accepted and *ignored* — a different
    failure from rejection, and one a boolean cannot express. The count is
    asserted as present and integral rather than non-zero, because the stub does
    not reproduce AWS's assessment shape; the live values are recorded in
    [V-29](../../docs/validation-log.md) as 2 for screen and 4 for verify.
    """
    probes = client.get("/api/diagnostics/sdk").json()["probes"]
    for site, probe in probes.items():
        assert isinstance(probe["assessments_with_action_none"], int), site


def test_the_sdk_diagnostics_endpoint_reports_no_model_invocation(client):
    """It probes ApplyGuardrail only, so it must cost no inference."""
    probes = client.get("/api/diagnostics/sdk").json()["probes"]
    assert all(p["model_invoked"] is False for p in probes.values())


def test_local_is_not_mistaken_for_lambda(monkeypatch, client):
    """AWS_EXECUTION_ENV is set by other tools; only the function name is reliable.

    The Q CLI sets AWS_EXECUTION_ENV=AmazonQ-For-CLI, which made the first version
    of this endpoint report a local shell as a Lambda runtime.
    """
    monkeypatch.setenv("AWS_EXECUTION_ENV", "AmazonQ-For-CLI Version/1.20.0")
    monkeypatch.delenv("AWS_LAMBDA_FUNCTION_NAME", raising=False)

    body = client.get("/api/diagnostics/sdk").json()
    assert body["environment"] == "local"
    assert body["lambda_runtime"] is None
    assert body["execution_env"] == "AmazonQ-For-CLI Version/1.20.0"


def test_lambda_is_detected_by_function_name(monkeypatch, client):
    monkeypatch.setenv("AWS_LAMBDA_FUNCTION_NAME", "kilimo-desk-api")
    monkeypatch.setenv("AWS_EXECUTION_ENV", "AWS_Lambda_python3.12")

    body = client.get("/api/diagnostics/sdk").json()
    assert body["environment"] == "lambda"
    assert body["lambda_runtime"] == "AWS_Lambda_python3.12"
    assert body["lambda_function"] == "kilimo-desk-api"


class MaskingBedrock(RecordingBedrock):
    """Screen returns the shape AWS actually sends for a masked prompt.

    One regex masked, and two managed entities that looked and allowed. That
    second half only exists because this demo sets `outputScope=FULL`, and it is
    what the Background_View shows as "a policy that looked and allowed"
    (validation log V-23). It is also what broke the pipeline: see V-31.
    """

    def apply_guardrail(self, **kw):
        self.calls.append(("apply_guardrail", kw["source"]))
        self.apply_requests.append(kw)
        if kw["source"] != "INPUT":
            return {"action": "NONE", "outputs": [], "assessments": []}
        return {
            "action": "GUARDRAIL_INTERVENED",
            "actionReason": "Guardrail masked.",
            "outputs": [{"text": self.masked_text}],
            "assessments": [
                {
                    "sensitiveInformationPolicy": {
                        "piiEntities": [
                            {"type": "PHONE", "action": "NONE", "match": ""},
                            {"type": "NAME", "action": "NONE", "match": ""},
                        ],
                        "regexes": [
                            {"name": "National ID", "action": "ANONYMIZED", "match": "24518803"},
                        ],
                    }
                }
            ],
        }


def test_a_masked_prompt_continues_even_when_other_policies_report_none():
    """The regression test for V-31.

    `action` is the string "NONE" for a policy that looked and allowed, and a
    non-empty string is truthy — so a filter written as `if hit.action` keeps
    those findings, and every one of them then fails an `== "ANONYMIZED"` test.
    The request was refused as though it had been blocked.

    The prompt below is the one the README and V-23 showcase, so the defect hit
    the demo's own headline example.
    """
    stub = MaskingBedrock(
        masked_text="My national ID is {National ID}, please check my membership status."
    )
    body = client_with(stub).post(
        "/api/ask",
        json={"input": "My national ID is 24518803, please check my membership status."},
    ).json()

    assert body["stopped_at"] is None, (
        "a masked request must continue — it was refused at "
        f"{body['stopped_at']!r} instead"
    )
    assert body["final"] != scenario.BLOCKED_INPUT_MESSAGE
    # All three stages ran, and the model saw only the rewritten text.
    assert [s["stage"] for s in body["stages"]] == ["screen", "answer", "verify"]
    assert "24518803" not in stub.all_converse_text()


def test_a_genuine_block_still_halts_when_a_policy_also_reports_none():
    """The other direction: NONE findings must not turn a block into a pass."""

    class BlockingBedrock(RecordingBedrock):
        def apply_guardrail(self, **kw):
            self.calls.append(("apply_guardrail", kw["source"]))
            self.apply_requests.append(kw)
            if kw["source"] != "INPUT":
                return {"action": "NONE", "outputs": [], "assessments": []}
            return {
                "action": "GUARDRAIL_INTERVENED",
                "outputs": [{"text": "unchanged"}],
                "assessments": [
                    {
                        "topicPolicy": {"topics": [
                            {"name": "Agrochemical Dosing", "action": "BLOCKED"}]},
                        "sensitiveInformationPolicy": {"piiEntities": [
                            {"type": "NAME", "action": "NONE", "match": ""}]},
                    }
                ],
            }

    stub = BlockingBedrock()
    body = client_with(stub).post(
        "/api/ask", json={"input": "How many millilitres of fungicide?"}
    ).json()

    assert body["stopped_at"] == "screen"
    assert stub.converse_count == 0
