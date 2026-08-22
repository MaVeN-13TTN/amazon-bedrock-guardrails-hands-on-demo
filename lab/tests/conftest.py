"""Shared stubs for the lab tests. No AWS credentials, no network."""
from __future__ import annotations

import pytest

from lab.core import Preflight


class FakeBedrock:
    """A bedrock-runtime stand-in whose verdict is configured per prompt."""

    def __init__(self, blocked_prompts=(), masked_prompts=(), grounding_fails=False):
        self.blocked = set(blocked_prompts)
        self.masked = set(masked_prompts)
        self.grounding_fails = grounding_fails
        self.apply_calls: list[dict] = []

    def apply_guardrail(self, **kw):
        self.apply_calls.append(kw)
        text = kw["content"][-1]["text"]["text"]

        if kw["source"] == "OUTPUT":
            action = "GUARDRAIL_INTERVENED" if self.grounding_fails else "NONE"
            score = 0.2 if self.grounding_fails else 0.95
            return {
                "action": action,
                "outputs": [],
                "assessments": [{"contextualGroundingPolicy": {"filters": [
                    {"type": "GROUNDING", "threshold": 0.7, "score": score,
                     "action": "BLOCKED" if self.grounding_fails else "NONE"},
                ]}}],
            }

        if text in self.blocked:
            return {
                "action": "GUARDRAIL_INTERVENED",
                "outputs": [],
                "assessments": [{"topicPolicy": {"topics": [
                    {"name": "Agrochemical Dosing", "action": "BLOCKED"}]}}],
            }
        if text in self.masked:
            # AWS reports masking as GUARDRAIL_INTERVENED with this actionReason,
            # not as NONE. A stub that returns NONE here encodes the very
            # assumption that caused the V-15 defect, and lets code that treats
            # every intervention as a block pass its tests.
            return {
                "action": "GUARDRAIL_INTERVENED",
                "actionReason": "Guardrail masked.",
                "outputs": [{"text": "I am {NAME}"}],
                "assessments": [{"sensitiveInformationPolicy": {"piiEntities": [
                    {"type": "NAME", "action": "ANONYMIZED"}]}}],
            }
        return {"action": "NONE", "outputs": [{"text": text}], "assessments": []}


class FlakyBedrock(FakeBedrock):
    """Intervenes on a fixed schedule, for probabilistic checkpoint tests."""

    def __init__(self, pattern: list[bool]):
        super().__init__()
        self.pattern = pattern
        self.index = 0

    def apply_guardrail(self, **kw):
        blocks = self.pattern[self.index % len(self.pattern)]
        self.index += 1
        if not blocks:
            return {"action": "NONE", "outputs": [], "assessments": []}
        return {
            "action": "GUARDRAIL_INTERVENED",
            "outputs": [],
            "assessments": [{"topicPolicy": {"topics": [
                {"name": "Agrochemical Dosing", "action": "BLOCKED"}]}}],
        }


class RaisingBedrock(FakeBedrock):
    def __init__(self, exc: Exception):
        super().__init__()
        self.exc = exc

    def apply_guardrail(self, **kw):
        raise self.exc


class FakeBedrockControl:
    """A bedrock control-plane stand-in for teardown tests."""

    def __init__(self, guardrails=None, delete_error=None, persist=False):
        self.guardrails = list(guardrails or [])
        self.delete_error = delete_error
        self.persist = persist
        self.deleted: list[str] = []

    def list_guardrails(self, **kw):
        return {"guardrails": list(self.guardrails)}

    def delete_guardrail(self, guardrailIdentifier):  # noqa: N803 — boto3 spelling
        if self.delete_error:
            raise self.delete_error
        self.deleted.append(guardrailIdentifier)
        if not self.persist:
            self.guardrails = [
                g for g in self.guardrails if g.get("id") != guardrailIdentifier
            ]


@pytest.fixture
def pf() -> Preflight:
    return Preflight(
        guardrail_id="test-guardrail",
        region="eu-west-1",
        guardrail_version="DRAFT",
        tier="STANDARD",
    )


@pytest.fixture
def service(pf):
    from lab.core import build_service

    return build_service(pf, client=FakeBedrock())
