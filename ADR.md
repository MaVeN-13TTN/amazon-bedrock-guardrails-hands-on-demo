# Architecture decision record

Decisions taken building this demo, with the reasoning and the consequences.
Numbered for reference; each stands alone.

Context throughout: a one-hour presented demo for the **AWS AI/ML User Group
Kenya**, deployed to a **single environment** in **eu-west-1**, that must survive
being driven live over a video call and be re-deployable by anyone who clones the
repo.

---

## 1. Guardrails as a three-stage pipeline, not a model wrapper

**Status:** accepted

**Context.** The obvious way to demonstrate Bedrock Guardrails is to attach one to
a `Converse` call and show blocked prompts in a chat window. That works, but it
teaches the wrong mental model: it makes a guardrail look like a model feature.
The product's actual design idea is that the policy engine is *independent* of
inference — `ApplyGuardrail` evaluates content without invoking any model.

**Decision.** Structure the application as three explicit stages:

| Stage | API | Model invoked |
|---|---|---|
| 1 · Screen | `ApplyGuardrail(source=INPUT)` | no |
| 2 · Answer | `Converse` + `guardrailConfig` | yes |
| 3 · Verify | `ApplyGuardrail(source=OUTPUT)` | no |

The UI renders all three side by side and each stage reports a `model_invoked`
flag, so a request rejected at stage 1 visibly leaves stages 2 and 3 untouched.

**Consequences.**
- The model-independence property is demonstrated rather than asserted: two of
  three stages provably never reach a foundation model.
- Rejecting at stage 1 costs no inference tokens and no model latency. That is a
  real production pattern, not a demo contrivance.
- Stage 1 and stage 2 overlap: input is evaluated twice when a request passes
  screening. In production you would pick one. Accepted here because the
  separation is the teaching point; noted in the runbook so it is not mistaken
  for an oversight.
- Three sequential Bedrock calls set the Lambda timeout floor (60 s) and make the
  happy path slower than a single guarded `Converse` would be.

## 2. Contextual grounding without a knowledge base

**Status:** accepted

**Context.** Contextual grounding is usually demonstrated on a RAG stack, which
is why short demos skip it — standing up a knowledge base and a vector store is
more setup than the rest of the demo combined.

**Decision.** Use `ApplyGuardrail`'s content qualifiers. The reference document is
passed inline at evaluation time:

```python
content=[
    {"text": {"text": bulletin,     "qualifiers": ["grounding_source"]}},
    {"text": {"text": question,     "qualifiers": ["query"]}},
    {"text": {"text": model_answer, "qualifiers": ["guard_content"]}},
]
```

**Consequences.**
- Five of six policy types are exercised with no extra infrastructure.
- Grounding and relevance can be shown as *independent* checks — including the
  instructive case of an answer that is factually correct and fully supported by
  the document, yet fails relevance because it does not address the question.
- The reference document is a nine-line string in `shared/scenario.json`, so every
  claim is checkable on screen. Real grounding sources are retrieved passages;
  this is the mechanism, not the retrieval pipeline.
- Not representative of grounding cost or latency at realistic document sizes.

## 3. FastAPI on Lambda behind an HTTP API, not Fargate

**Status:** accepted

**Context.** The backend is request/response, holds no state, and is idle except
when someone is presenting. Options were Lambda + API Gateway, ECS Fargate + ALB,
or App Runner.

**Decision.** Lambda (python3.12, arm64) with Mangum adapting FastAPI to API
Gateway HTTP API payload format 2.0.

**Consequences.**
- Scales to zero. A cloned repo costs nothing when idle, which matters for a demo
  people are invited to redeploy.
- One `terraform apply`, no VPC, no load balancer, no container registry. Bedrock
  is a public IAM-authenticated endpoint, so no networking is required.
- Same code runs under `uvicorn` locally and in Lambda; no branching.
- Cold starts are real. First request after idle pays ~1–2 s on top of three
  Bedrock calls. The runbook says to send one warm-up request before presenting.
- Response streaming is off the table through API Gateway. This app uses
  `Converse`, not `ConverseStream`, so nothing is lost today — but adding token
  streaming later means Lambda Function URLs or a different compute choice.
- arm64 requires dependencies built for `manylinux2014_aarch64`, so packaging
  cannot just copy the host's site-packages. See decision 8.

## 4. Next.js as a static export

**Status:** accepted

**Context.** The requirement is Next.js on Amplify Hosting. Amplify supports SSR
via `WEB_COMPUTE`, and static hosting via `WEB`.

**Decision.** `output: "export"` — a fully static bundle, served by Amplify as a
CDN with no SSR compute.

**Consequences.**
- The frontend is a browser client that calls the API directly. There is no server
  component, so there is nothing to secure, scale, or cold-start on the web tier.
- Manual deployment works reliably: the bundle is a zip pushed through
  `create-deployment` / `start-deployment`, so **no GitHub personal access token
  is required** to deploy. Connecting a repository stays available via
  `amplify_repository_url` for CI builds.
- `NEXT_PUBLIC_API_BASE_URL` is baked in at build time. Changing the API URL means
  rebuilding the frontend, which `scripts/deploy-frontend.sh` does automatically
  by reading the Terraform output.
- No server-side rendering means no request-time secrets and no server-side data
  fetching. Not a constraint for this app; would be for a real product needing SEO
  or per-user server rendering.
- A static export has no router on the server, so a `404-200` rewrite to
  `index.html` is required for deep links.

## 5. One policy definition in `shared/scenario.json`

**Status:** accepted

**Context.** The guardrail policy is needed in two places: Terraform creates the
guardrail from it, and the backend serves the system prompt, reference bulletin
and blocked-request messages from it. An earlier iteration had a Python module and
a Terraform block that both described the same topics — two copies guaranteed to
drift.

**Decision.** A single JSON file read by both. Terraform uses
`jsondecode(file(...))` with `dynamic` blocks; the backend loads it at runtime and
the packaging step copies it into the Lambda bundle.

**Consequences.**
- Editing the scenario is one file plus `terraform apply`. Denied topics, PII
  regexes, thresholds and prose all live together.
- Terraform is the authority for what is *deployed*; the backend only reads the
  policy for display on `/api/context`. The guardrail is never created from Python.
- JSON has no comments, so explanation lives in a `_comment` key and in the
  loader's docstring. Regex patterns need JSON escaping (`\\b`), which is easy to
  get wrong — the smoke test covers the national-ID regex for that reason.
- Re-skinning the demo for a different audience is a single-file change.

## 6. The API is unauthenticated, with throttling as the cost guard

**Status:** accepted — **with a known limitation**

**Context.** The endpoint proxies to Bedrock. An open endpoint that spends money
per request is an abuse risk. Full Cognito with a hosted UI and a JWT authorizer
would fix it, at the cost of a sign-in flow in the demo path and significantly
more that can fail live.

**Decision.** Ship without authentication for this single-environment demo, and
bound the damage instead:

- API Gateway stage throttling at 10 rps / 20 burst (tunable via variables).
- CORS restricted to the Amplify branch URL and `localhost:3000`, not `*`.
- `max_input_chars` rejects oversized prompts in the app before Bedrock is called.
- CloudWatch alarms on Lambda errors and throttles.

**Consequences.**
- **This is the weakest point in the stack and should be stated plainly rather
  than discovered.** Anyone who finds the URL can spend Bedrock tokens up to the
  throttle ceiling. CORS is browser-enforced and does not stop a direct client.
- Acceptable for a short-lived demo whose URL is shared with a meetup and torn
  down afterwards. **Not acceptable for anything longer-lived.**
- The migration path is contained: add a Cognito user pool, a
  `aws_apigatewayv2_authorizer` of type `JWT`, and `authorizer_id` on the routes.
  The frontend already funnels every call through `src/lib/api.ts`, so attaching a
  token is one file.
- If this is left running, put a budget alarm on the account.

## 7. Local Terraform state

**Status:** accepted

**Context.** Single environment, single operator.

**Decision.** Default local backend; no S3 bucket, no DynamoDB lock table.

**Consequences.**
- Nothing to bootstrap before the first `apply`.
- State lives on one machine. No locking, no history, no collaboration. Losing the
  file means importing or recreating resources.
- Moving to a shared backend is a `backend "s3"` block plus `terraform init
  -migrate-state`, flagged in `versions.tf`.

## 8. Terraform drives Lambda packaging

**Status:** accepted

**Context.** arm64 Lambda needs Linux/aarch64 wheels. `pip install` on the
developer's machine produces host-architecture binaries, and `pydantic-core` ships
a compiled extension — the wrong wheel fails at import, at runtime, with a
traceback that does not mention architecture.

**Decision.** `scripts/package-backend.sh` installs with explicit
`--platform manylinux2014_aarch64 --only-binary=:all:`, and a `null_resource`
triggered by a hash of the backend source and the scenario file runs it. A
`data.archive_file` with `depends_on` zips the result — the dependency defers the
data source to apply time, so `terraform apply` is self-contained.

**Consequences.**
- One command deploys everything; no "remember to build first" step.
- The script is independently runnable for local iteration.
- `boto3`/`botocore` are stripped from the bundle because the Lambda runtime
  provides them. Bundle is ~8.7 MB instead of ~30 MB, so cold starts are shorter.
  The trade-off is that the runtime's boto3 version, not `requirements.txt`,
  decides which Bedrock API shapes are available — a real risk when a new
  guardrail field ships. If a field is missing, add boto3 back to the bundle.
- `--only-binary=:all:` fails loudly if any dependency lacks an aarch64 wheel,
  which is better than silently shipping a broken one.
- Requires `bash` and `python3` on the machine running Terraform.

## 9. AWS provider v6, and `tier_config` is an attribute

**Status:** accepted

**Context.** `aws_bedrock_guardrail` in provider 5.x does not support
`tier_config`, `cross_region_config`, or the PII `input_action`/`output_action`
fields. The STANDARD/CLASSIC tier distinction is central to this demo, so 5.x is
not viable.

**Decision.** Pin `~> 6.0` (tested on 6.61.0).

**Consequences.**
- `tier_config` is a **list attribute** in this version, not a nested block:
  `tier_config = [{ tier_name = "STANDARD" }]`. The provider's published examples
  show block syntax from a later revision; block syntax fails to validate here.
- STANDARD tier requires `cross_region_config.guardrail_profile_identifier`. The
  profile follows `<geo>.guardrail.v1:0` and is a variable, because coverage is
  Region-dependent and changes.
- Switching tier is `-var guardrail_tier=CLASSIC` and a re-apply, which is how the
  runbook demonstrates the tier gap live.

## 10. eu-west-1 requires a cross-Region inference profile

**Status:** accepted

**Context.** In eu-west-1, current Claude models are not served on a bare model
ID. `bedrock:InvokeModel` with `anthropic.claude-haiku-4-5-...` fails with
*"Invocation with on-demand throughput isn't supported"*.

**Decision.** Default `bedrock_model_id` to
`eu.anthropic.claude-haiku-4-5-20251001-v1:0` — the EU cross-Region inference
profile — and document why the prefix is load-bearing.

**Consequences.**
- The IAM policy must permit `InvokeModel` on **both** the inference-profile ARN
  and the underlying foundation-model ARNs (which carry no account id and span
  Regions), because the profile fans out. Getting only one of the two produces an
  `AccessDeniedException` that reads like a model-access problem.
- Requests may be served from another EU Region. The data stays within the EU
  geography, which is the relevant consideration for a data-residency story.
- Using `af-south-1` (Cape Town) instead would need its own profile and model
  availability check. Automated Reasoning checks are unavailable there; they are
  available in eu-west-1, though this demo does not use them.

## 11. Automated Reasoning checks are out of scope

**Status:** accepted

**Context.** It is the sixth policy type and the only one offering formal
guarantees rather than probabilistic risk reduction.

**Decision.** Not configured.

**Consequences.**
- It requires a source policy document, which Bedrock converts to formal logic
  that you then test and refine. That is a workshop of its own, not a segment.
- It is English-only, unavailable in several Regions, and does not support
  streaming APIs.
- The runbook covers it verbally in the limits section, where the honest framing
  belongs: every other policy reduces risk probabilistically; only this one proves
  anything, and only against the policy you supplied.
