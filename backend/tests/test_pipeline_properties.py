"""Pipeline invariants, stated as properties.

The demo's two strongest claims are that a rejected request costs no inference and
that masked text is what the model receives. Both were carried by a label in the
UI and a weak test. These hold them for every input, not one example, because they
are the moments the session is built around.
"""
from fastapi.testclient import TestClient
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.config import Settings
from app.guardrails import GuardrailService
from app.main import app, get_service, get_settings
from tests.test_api import RecordingBedrock

SUPPRESS_FIXTURE_CHECK = settings(
    max_examples=30,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)


def client_with(stub, **overrides) -> TestClient:
    cfg = Settings(guardrail_id="test-guardrail", guardrail_enabled=True, **overrides)
    app.dependency_overrides[get_settings] = lambda: cfg
    app.dependency_overrides[get_service] = lambda: GuardrailService(cfg, client=stub)
    return TestClient(app)


def teardown_function() -> None:
    app.dependency_overrides.clear()


# Text that will not itself trip the length guard, of the full permitted range.
prompts = st.text(min_size=1, max_size=2000).filter(lambda s: s.strip())


@given(prompts)
@SUPPRESS_FIXTURE_CHECK
def test_a_screened_block_never_reaches_the_model(text):
    """For all inputs that are blocked at screen: zero model calls, one stage."""
    stub = RecordingBedrock(screen_blocks=True)
    body = client_with(stub).post("/api/ask", json={"input": text}).json()

    assert stub.converse_count == 0
    assert len(body["stages"]) == 1
    assert body["stages"][0]["stage"] == "screen"
    assert body["stopped_at"] == "screen"


@given(
    st.sampled_from(["HG-004182", "HG-999999"]),
    st.sampled_from(["0722135790", "0733000111"]),
)
@SUPPRESS_FIXTURE_CHECK
def test_an_anonymised_value_never_appears_in_the_converse_request(member_no, phone):
    """For all inputs carrying a masked value, that value is absent from the request.

    Not merely absent from guardContent — absent from every text field, so a value
    cannot leak through the system prompt or an inference parameter either.
    """
    stub = RecordingBedrock(masked_text="I am {NAME}, member {UUID}, number {PHONE}")
    client_with(stub).post(
        "/api/ask",
        json={"input": f"I am Grace Wanjiku, member {member_no}, my number is {phone}"},
    )

    sent = stub.all_converse_text()
    assert member_no not in sent
    assert phone not in sent
    assert "Grace Wanjiku" not in sent


@given(st.sampled_from([
    ("screen", {"screen_blocks": True}),
    ("answer", {"answer_blocks": True}),
    ("verify", {"verify_blocks": True}),
    (None, {}),
]))
@SUPPRESS_FIXTURE_CHECK
def test_model_invoked_is_true_only_for_the_answer_stage(case):
    """Whichever stage halts, only stage 2 ever reports a model call."""
    halting, kwargs = case
    stub = RecordingBedrock(**kwargs)
    body = client_with(stub).post("/api/ask", json={"input": "a question"}).json()

    for stage in body["stages"]:
        assert stage["model_invoked"] is (stage["stage"] == "answer")
    assert body["stopped_at"] == halting


@given(st.integers(min_value=2001, max_value=4000))
@SUPPRESS_FIXTURE_CHECK
def test_over_limit_input_makes_no_aws_call_at_all(length):
    """For all over-limit inputs: zero ApplyGuardrail and zero Converse calls."""
    stub = RecordingBedrock()
    r = client_with(stub).post("/api/ask", json={"input": "x" * length})

    assert r.status_code == 422
    assert stub.calls == []
    assert "2000" in r.text


def test_an_answer_block_skips_the_verify_call():
    """A blocked answer has nothing to ground-check, so stage 3 must not run."""
    stub = RecordingBedrock(answer_blocks=True)
    body = client_with(stub).post("/api/ask", json={"input": "a question"}).json()

    assert stub.verify_count == 0
    assert [s["stage"] for s in body["stages"]] == ["screen", "answer"]
    assert body["stopped_at"] == "answer"


def test_a_clean_request_runs_three_stages_in_order_with_no_halt():
    stub = RecordingBedrock()
    body = client_with(stub).post("/api/ask", json={"input": "a question"}).json()

    assert [s["stage"] for s in body["stages"]] == ["screen", "answer", "verify"]
    assert body["stopped_at"] is None
    assert body["total_latency_ms"] == sum(s["latency_ms"] for s in body["stages"])


def test_verify_supplies_three_qualified_blocks_with_the_question_as_asked():
    """Relevance is judged against the question the member actually asked.

    So the query block carries the submitted text with whitespace stripped and
    screen-stage rewriting NOT applied — if it carried the masked text, an
    anonymised question would score as irrelevant to its own answer.
    """
    stub = RecordingBedrock(masked_text="I am {NAME}")
    client_with(stub).post("/api/ask", json={"input": "  I am Grace, when do I get paid?  "})

    verify_request = next(r for r in stub.apply_requests if r["source"] == "OUTPUT")
    blocks = verify_request["content"]
    assert len(blocks) == 3

    by_qualifier = {b["text"]["qualifiers"][0]: b["text"]["text"] for b in blocks}
    assert set(by_qualifier) == {"grounding_source", "query", "guard_content"}
    assert by_qualifier["query"] == "I am Grace, when do I get paid?"
    assert "Kangema" in by_qualifier["grounding_source"]
    assert by_qualifier["guard_content"] == "Kangema opens 06:00 to 10:00."


def test_empty_rewritten_text_falls_back_to_the_submitted_input():
    """If screen returns no text, the model must still get the question."""
    stub = RecordingBedrock(masked_text="")
    client_with(stub).post("/api/ask", json={"input": "When do points open?"})

    assert stub.guard_text() == "When do points open?"
