# Kilimo Desk — a hands-on Amazon Bedrock Guardrails demo

A full-stack demo of **Amazon Bedrock Guardrails**, built for the **AWS AI/ML User
Group Kenya** monthly meetup. It shows what a guardrail actually does inside a
generative AI application — not as a checkbox on a model call, but as an
independent policy engine you can invoke on its own.

The app is **Kilimo Desk**, the member-support assistant for *Highland Growers
Co-operative*, a fictional smallholder farming co-operative in **Murang'a County**.
The domain is deliberate: a wrong answer here has consequences you can name out
loud. A bad chemical dose harms a crop, an animal, or a person.

![Architecture](docs/architecture.svg)

- **[RUNNING.md](RUNNING.md)** — prerequisites, deploy, local development, troubleshooting
- **[ADR.md](ADR.md)** — architecture decisions and their consequences
- **[docs/demo-runbook.md](docs/demo-runbook.md)** — the 60-minute presented session
- **[docs/further-reading.md](docs/further-reading.md)** — official samples, articles, docs

---

## The idea: guardrails as a three-stage pipeline

Most guardrail demos are a chat box with a policy attached. That teaches the wrong
mental model — it makes a guardrail look like a feature of the model. It isn't.
This demo splits the work into three stages, because the split *is* the lesson:

| Stage | API | Model invoked? | What it shows |
|---|---|---|---|
| **1 · Screen** | `ApplyGuardrail(source=INPUT)` | **no** | reject bad input before paying for inference |
| **2 · Answer** | `Converse` + `guardrailConfig` | yes | the convenience path when you're already on Bedrock |
| **3 · Verify** | `ApplyGuardrail(source=OUTPUT)` | **no** | is the answer grounded in the reference document? |

Two of three stages never invoke a foundation model. The same screening call could
front a self-hosted model or a third-party API, because evaluation is independent
of inference — and here that is demonstrated, not asserted.

The UI renders all three stages side by side, each reporting whether it called a
model and how long it took. Reject a request at stage 1 and you watch stages 2
and 3 grey out, having cost nothing.

## What's in the box

```
frontend/         Next.js 15 (App Router, TypeScript, Tailwind) — static export
backend/          FastAPI — runs under uvicorn locally, Lambda via Mangum deployed
infrastructure/   Terraform — guardrail, Lambda, HTTP API, Amplify, IAM, alarms
shared/           scenario.json — one policy definition, read by Terraform and the app
scripts/          package-backend.sh · deploy-frontend.sh · smoke-test.sh
docs/             architecture diagram, runbook, further reading
```

| Path | What it is |
|---|---|
| [`shared/scenario.json`](shared/scenario.json) | **the policy** — persona, denied topics, PII rules, thresholds, reference bulletin. One file, no second copy. |
| [`backend/app/guardrails.py`](backend/app/guardrails.py) | **the mechanics** — `screen()`, `answer()`, `verify()` and assessment parsing |
| [`backend/app/main.py`](backend/app/main.py) | FastAPI routes and AWS error mapping |
| [`infrastructure/guardrail.tf`](infrastructure/guardrail.tf) | the guardrail, built from `scenario.json` with `dynamic` blocks |
| [`frontend/src/components/StageCard.tsx`](frontend/src/components/StageCard.tsx) | one pipeline stage in the UI |
| [`docs/architecture.svg`](docs/architecture.svg) | the diagram above — presentation-ready |

## Quick start

Full detail in **[RUNNING.md](RUNNING.md)**. The short version, after enabling
Claude Haiku 4.5 in Bedrock for **eu-west-1**:

```bash
cd infrastructure
cp terraform.tfvars.example terraform.tfvars
terraform init && terraform apply          # builds the Lambda bundle too

cd ..
./scripts/deploy-frontend.sh               # build Next.js, push to Amplify
./scripts/smoke-test.sh                    # verify end to end

terraform -chdir=infrastructure output frontend_url
```

## Policies configured

Five of the six policy types, chosen by the domain rather than to tour the product:

| Policy | Configuration | Why this one |
|---|---|---|
| **Denied topics** | `Agrochemical Dosing`, `Land Tenure Disputes`, `Credit Terms` | each maps to a real harm or a regulated activity, written as natural-language definitions rather than keyword lists |
| **Content filters** | 6 categories at HIGH; `PROMPT_ATTACK` input-only | baseline moderation |
| **Word filters** | 2 unannounced internal programme names + managed profanity list | leak prevention — a different job from topic denial |
| **Sensitive information** | `PHONE`, `NAME` → ANONYMIZE; custom regexes for a co-op member number and a Kenyan national ID | data minimisation at the boundary |
| **Contextual grounding** | grounding ≥ 0.7, relevance ≥ 0.7 | hallucination control |
| ~~Automated Reasoning~~ | not configured | needs a formal policy document; English-only; Region-limited. See [ADR decision 11](ADR.md) |

### PII masked before the model sees it

`ANONYMIZE` is the API's name for the console's *Mask*, and setting `input_action`
means the value is replaced **before the model receives it**. Send:

> I am Grace Wanjiku, member HG-004182, my number is 0722135790. Has my payment gone out?

Stage 1 reports three separate hits — `NAME`, `PHONE`, and the `Co-op Member
Number` regex — and shows the rewritten string that gets forwarded. The request is
**not blocked**; it continues with the personal data removed. Blocking and masking
are different tools, and this is the difference. It is also the shape of control
Kenya's Data Protection Act 2019 asks for: minimisation at the boundary, not
redaction bolted on afterwards.

### Contextual grounding without a knowledge base

Grounding normally implies a RAG stack, which is why short demos skip it.
`ApplyGuardrail` takes the reference document inline, tagged with a qualifier:

```python
content=[
    {"text": {"text": bulletin,     "qualifiers": ["grounding_source"]}},
    {"text": {"text": question,     "qualifiers": ["query"]}},
    {"text": {"text": model_answer, "qualifiers": ["guard_content"]}},
]
```

Grounding and relevance are **independent** checks. The instructive case is an
answer that is factually correct *and* fully supported by the bulletin, yet still
fails — because it does not address the question asked. The UI's *Grounding check*
tab has one canned case for each outcome.

## How the guardrail attaches to a model call

Stage 2, in [`backend/app/guardrails.py`](backend/app/guardrails.py):

```python
self._client.converse(
    modelId=self.settings.bedrock_model_id,
    system=[{"text": scenario.SYSTEM_PROMPT}],
    messages=[{"role": "user",
               "content": [{"guardContent": {"text": {"text": user_text}}}]}],
    guardrailConfig={
        "guardrailIdentifier": self.settings.guardrail_id,
        "guardrailVersion": self.settings.guardrail_version,
        "trace": "enabled",
    },
)
```

Three things worth knowing:

- **`guardContent` is selective.** Only the wrapped span is evaluated, so the
  system prompt's own boundary rules never trip the filters.
- **`trace: "enabled"` is not optional.** Without it you learn *that* a request
  was blocked, never *which policy* blocked it — and every panel in this UI is
  built from that trace.
- **A block is not an exception.** `converse()` returns normally with
  `stopReason == "guardrail_intervened"` and the configured message as the text.

The two APIs also report differently, which the parser normalises: `apply_guardrail`
returns a flat `assessments` list, while `converse` returns a `trace` where
`inputAssessment` maps guardrail-id → *one* assessment but `outputAssessments`
maps guardrail-id → a **list**. `backend/tests/test_parsing.py` pins both shapes.

## Two things that will bite you

**In eu-west-1 the `eu.` prefix is load-bearing.** Current Claude models are not
served on a bare model ID there — `anthropic.claude-haiku-4-5-...` fails with
*"Invocation with on-demand throughput isn't supported"*. Use the cross-Region
inference profile, `eu.anthropic.claude-haiku-4-5-20251001-v1:0`. The IAM policy
then has to permit `InvokeModel` on **both** the profile ARN and the underlying
foundation-model ARNs, because the profile fans out.

**The tier default is the weak one.** Content filters and denied topics run in
`CLASSIC` or `STANDARD`. CLASSIC covers English, French and Spanish only. STANDARD
adds ~60 languages, better recall on manipulated input, and detection of harmful
content inside code elements — and requires cross-Region inference. Anyone
shipping something multilingual who leaves the default in place will conclude the
guardrail is broken. Switching is one variable:

```bash
terraform apply -var guardrail_tier=CLASSIC   # Swahili prompt attack sails through
terraform apply -var guardrail_tier=STANDARD  # same prompt, blocked
```

## What Guardrails does not do

Worth saying out loud, because it is the most common misunderstanding:

- It is **not authentication or authorisation.** It does not know who the member is
  or what they are entitled to see.
- It evaluates **content, not actions.** If your agent holds a tool that can write
  to the payments ledger, a guardrail on the text will not stop the call.
- It is not a substitute for input validation in your own application layer.
- It reduces risk **probabilistically** for most policy types. Only Automated
  Reasoning checks offer formal guarantees, and only against the policy you supply.

Guardrails is the content boundary in a defence-in-depth design, not the whole
security posture. The `bedrock:GuardrailIdentifier` IAM condition key is what turns
it from a suggestion a developer can forget into an organisational control.

## Known limitations

- **The API is unauthenticated**, bounded by throttling and a CORS allow-list
  rather than identity. Fine for a short-lived demo; not for anything longer.
  Rationale and the migration path are in [ADR decision 6](ADR.md).
- **Terraform state is local** — single operator, no locking ([decision 7](ADR.md)).
- **Cold starts** add 1–2 s to the first request ([decision 3](ADR.md)).
- **Stages 1 and 2 both evaluate the input** when a request passes screening. In
  production you would pick one; the separation is the teaching point ([decision 1](ADR.md)).
- **No response streaming** through API Gateway. Not needed today, but it
  constrains adding token streaming later ([decision 3](ADR.md)).

## Attribution

The scenario, policy set, pipeline architecture, application code, infrastructure
and test suite are original to this repository. AWS publishes its own
[self-paced workshop](https://catalog.workshops.aws/workshops/53c38a96-45e0-4019-967a-c73dcbe7a839/en-US)
on Bedrock Guardrails — a good follow-up for attendees, and not the basis of this
demo. Further reading is in [docs/further-reading.md](docs/further-reading.md).

Highland Growers Co-operative, Kilimo Desk, Project Tumaini, Batch Ledger v2 and
Extension Bulletin 14 are fictional. Any resemblance to a real co-operative is
coincidental.
