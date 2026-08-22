"""Kilimo Desk lab — the self-paced path an attendee runs on their own account.

Deliberately smaller than the deployed demo. It creates one billable resource, an
`aws_bedrock_guardrail`, and calls `ApplyGuardrail` only: no Lambda, no API
Gateway, no Amplify, and no foundation model. That is possible because two of the
three pipeline stages never invoke a model, which is also the demo's whole point.

It reuses `GuardrailService.screen()` and `.verify()` and the assessment parser
from `backend/app` rather than reimplementing them, so an attendee's lab result
and the deployed demo's behaviour come from the same code. It imports nothing
from FastAPI.
"""
