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

**Rejected alternative.** A single `Converse` call with `guardrailConfig` attached, which
is how most guardrail demos are built. Rejected because it teaches the wrong mental
model: it makes a guardrail look like a parameter of a model call, so a reader concludes
they cannot evaluate content without paying for inference. Splitting the stages costs one
extra API call per request and is the only reason the "rejected input costs no inference"
claim is visible rather than asserted.

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

**Rejected alternative.** A Bedrock Knowledge Base over the bulletin, with grounding
checked against retrieved passages. Rejected on setup cost: an OpenSearch Serverless
collection is roughly $700/month idle, dwarfing the whole demo, and it would make
grounding look like a feature of RAG rather than of the guardrail. The inline
`grounding_source` qualifier does the same job with no infrastructure.

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

**Rejected alternative.** Fargate behind an ALB, which removes cold starts and allows
response streaming. Rejected on idle cost and teardown risk: a task and an ALB bill
hourly whether or not anyone visits, which for a demo left running over a weekend is real
money. Lambda's 1–2 second cold start is a visible cost, and honest about the trade.

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

**Rejected alternative.** Next.js with SSR on Amplify Hosting's compute, or on Lambda via
an adapter. Rejected because the frontend has nothing to render server-side — every
request goes to a separate API — so SSR would add a runtime to pay for and debug in
exchange for nothing. The consequence is that the browser calls the API directly, which
is why CORS is load-bearing here.

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

**Rejected alternative.** Terraform variables as the source of truth, with the backend
reading its own copy. Rejected because two copies of a policy definition drift, and the
failure is silent: the guardrail enforces one thing while the UI describes another. That
is not hypothetical — validation found a related silent failure where a policy was
present but inert ([V-19](docs/validation-log.md)).

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

**Rejected alternative.** Cognito with a hosted UI, or an API key. Cognito was rejected
as disproportionate: a user pool, an app client and a login flow for a demo nobody has an
account on, and it would put a sign-in page in front of the member view the demo exists
to show. An API key was rejected as worse than nothing — it would appear in the static
bundle, so it would look like authentication without being any.

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

**Rejected alternative.** An S3 backend with DynamoDB locking. Rejected because it needs
two more resources created before the first `apply`, which is exactly the friction the
lab is designed to avoid, for a benefit — concurrent operators — that a single-presenter
demo does not have. Anyone extending this to a team should add it; the migration is one
`backend` block.

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

**Rejected alternative.** A committed `lambda.zip`, or a separate build step in CI.
Committing a binary was rejected because it goes stale silently and bloats the
repository. A separate CI step was rejected because `terraform apply` would then succeed
against a stale bundle — the failure mode being a deployed Lambda that does not match the
source you are reading.

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

**Rejected alternative.** Provider 5.x with a `null_resource` calling the AWS CLI to
configure the tier. Rejected because it puts the guardrail's most interesting
property outside Terraform's state, so a drift is invisible.

### Amendment, 2026-08-22 — both syntaxes validate; the profile id is wrong

Two consequences above are corrected. The original statements are retained.

**Corrected: block syntax does not fail.** The claim that *"block syntax fails to
validate here"* is wrong. Against provider 6.61.0, **both** spellings validate with
exit status zero:

```hcl
tier_config = [{ tier_name = var.guardrail_tier }]   # as committed — exit 0
tier_config { tier_name = var.guardrail_tier }       # nested block  — exit 0
```

The provider schema explains why. Within `content_policy_config`, `tier_config` is
declared as an **attribute**, not a block type:

```json
"attributes": { "tier_config": { "type": ["list", ["object", {"tier_name": "string"}]] } },
"block_types": ["filters_config"]
```

Terraform accepts block syntax for a list-of-object attribute for backward
compatibility, so both parse to the same value. **The decision's title and substance
are confirmed** — `tier_config` *is* an attribute, per the schema. What was wrong was
asserting the alternative fails. The list form is retained as canonical for an
attribute, not as the only option. Validation log V-04.

**Corrected: the profile identifier is not a bare id.** The claim that the profile
*"follows `<geo>.guardrail.v1:0`"* does not survive `terraform plan`:

```
Error: Invalid ARN Value
Path: cross_region_config[0].guardrail_profile_identifier
Value: eu.guardrail.v1:0
```

Provider 6.61.0 validates this as an ARN. The committed default therefore fails
**offline, for anyone**, whenever `guardrail_tier = STANDARD` — which is the default.
The correct value is presumed to be
`arn:aws:bedrock:<region>:<account>:guardrail-profile/eu.guardrail.v1:0`, but this is
**unverified**: `aws bedrock list-guardrail-profiles` does not exist in aws-cli
2.36.14 (V-01), so the identifier cannot be listed, and STANDARD-tier creation was
blocked by absent tag permissions (V-13). Labelled unverified per Requirement 10.11
rather than replaced with a second untested guess. Validation log V-05.

**Unchanged.** Pinning `~> 6.0` remains correct, and CLASSIC-tier apply is unaffected
— the `dynamic "cross_region_config"` block emits nothing at that tier, so the ARN is
never evaluated.

### Amendment, 2026-08-22 — Terraform needs three tag permissions

Not anticipated by the original decision. `versions.tf` sets a provider-level
`default_tags` block, so every resource is tagged on creation, and the provider reads
tags back when refreshing state. Managing an `aws_bedrock_guardrail` therefore needs:

```
bedrock:TagResource
bedrock:UntagResource
bedrock:ListTagsForResource
```

Without them the failure is unusually unhelpful: `apply` fails on `TagResource`;
removing `default_tags` lets it apply **once**; every later `plan` then fails on
`ListTagsForResource`. The guardrail exists and is unmanageable, while every
read-only permission check passes. `lab doctor --probe-write` detects this by
retrying an untagged create, which isolates a tagging gap from a create gap.
Validation log V-13.

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

**Rejected alternative.** A provisioned-throughput commitment would allow the bare
model ID, and was rejected as absurd for a demo — it bills hourly whether or not a
request arrives.

### Amendment, 2026-08-22 — the default is now the `global.` profile

The decision above is **superseded in one respect**: the default is now
`global.anthropic.claude-haiku-4-5-20251001-v1:0`. The original statement is
retained because its reasoning was sound and its central claim was confirmed.

**What validation confirmed.** The bare model ID is rejected in eu-west-1, with the
message quoted above almost verbatim (validation log V-08). It is also rejected in
us-east-1, so the behaviour is not Region-specific.

**What validation contradicted.** The consequence "requests may be served from
another EU Region" is true, and turned out to be a stronger constraint than
"acceptable for a data-residency story" implies. A `Converse` call in eu-west-1
through the `eu.` profile failed with:

```
is not authorized to perform: bedrock:InvokeModel
on resource: arn:aws:bedrock:eu-north-1::foundation-model/anthropic.claude-haiku-4-5-...
with an explicit deny in a service control policy
```

The request was routed to eu-north-1 and denied by an organisation SCP. An SCP is a
boundary no identity-based policy can widen, so no IAM change fixes it — and the
failure names a Region the caller never asked for, which reads as a
misconfiguration rather than a policy boundary (validation log V-09).

**What changed.** eu-west-1 offers two ACTIVE Haiku 4.5 profiles, and they differ in
where inference runs:

| Profile | Routes to |
|---|---|
| `eu.` | eu-central-1, eu-north-1, eu-south-1, eu-south-2, eu-west-1, eu-west-3 |
| `global.` | eu-west-1 only |

`global.` is now the default because a profile that resolves to a single Region
cannot route a request into a Region the organisation denies (validation log V-11).

**The lesson this strengthens.** The original entry taught that the prefix is
load-bearing. It is, and there is a second half: *which* prefix you choose
determines whether your organisation's Region controls permit the call at all. A
fan-out profile trades predictability for availability, and in an SCP-constrained or
data-residency-constrained account that trade is not free. Pinning inference to one
Region is what makes the request's Region a property of your configuration rather
than of AWS's routing.

**Unchanged.** The IAM consequence still holds, and `infrastructure/iam.tf` already
handles it: its prefix-stripping regex is `^(eu|us|apac|global)\.`, so it builds both
the foundation-model and inference-profile ARNs correctly for either profile. That
was verified against `terraform replace()` rather than assumed.

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

**Rejected alternative.** Configuring Automated Reasoning with a minimal policy document
just to show the sixth policy type. Rejected because a shallow demonstration of a formal
method is worse than none: it would suggest the guarantees are cheap, when the work is
writing the policy document, and it would fail in the Regions where the feature is
unavailable — including for attendees following along.


---

## 12. Replay_Mode sits above the boto3 client, not inside it

**Status:** accepted

**Context.** A presented demo fails in ways rehearsal does not catch: credentials expire
between rehearsal and delivery, model access is revoked, an organisation policy is
tightened, the venue's network is hostile. This project met three of those four during
validation ([V-06](docs/validation-log.md), [V-12](docs/validation-log.md)). A demo that
cannot survive a dead AWS account is a demo that will one day be delivered as a slideshow
of screenshots.

The requirement was specific: **all three stages complete with no credentials present and
Bedrock unreachable.**

**Decision.** Fixtures are consulted inside `GuardrailService`, *above* the boto3 client.
When `REPLAY_MODE=true`, `self._client` is `None` — no client is constructed at all — and
each stage method returns a recorded `StageResult` before any AWS code path is reached.
Fixtures are recorded from live responses by `python -m lab conformance --record`, never
hand-written, and each carries the date, Region, tier and guardrail version of its capture.

**Consequences.**
- The pipeline runs with `AWS_CONFIG_FILE=/dev/null` and every AWS variable unset. That is
  not incidental — `scripts/replay-check.sh` asserts it, and a unit test replaces
  `boto3.client` with a function that fails the test if called.
- The recorder had to respect the masking distinction of [V-15](docs/validation-log.md).
  A recorder that treats every `GUARDRAIL_INTERVENED` as a halt records the PII case as
  stopping at screen, which makes the demo's most instructive case unreplayable. The same
  `_continues()` predicate now governs both the pipeline and the recorder.
- An unmatched prompt is a **409 listing the recorded prompts**, not a 500. Nothing is
  broken; the prompt was simply not captured, and the presenter needs to know which ones
  were.
- The replay indicator lives in the disclosure bar **outside** the Chat_Window. A
  "recorded" label inside an assistant turn would show the audience something no real
  member would ever see, which would undo precisely what the member view exists to
  demonstrate.

**Rejected alternative 1.** Patching the boto3 response with a stub client, the usual
testing approach. Rejected because client construction itself consults the credential chain
and needs a Region: `boto3.client("bedrock-runtime", region_name="")` fails before any
response could be stubbed. A stub satisfies a test suite and fails the actual requirement.

**Rejected alternative 2.** Recording at the HTTP layer with a cassette library such as VCR
or `botocore.stub`. Rejected for the same reason plus a second: a cassette is keyed on
serialised request bodies, so it breaks when an SDK upgrade changes the wire format —
exactly the SDK-version fragility [V-14](docs/validation-log.md) and
[V-24](docs/validation-log.md) already made this project pay for twice.

**Rejected alternative 3.** Hand-writing the fixtures, which would have been faster than
building `--record`. Rejected because a hand-written fixture encodes what the author
believes AWS returns, and this repository has documented nine cases where that belief was
wrong. The masking `actionReason`, the `{Co-op Member Number}` placeholder naming, and the
0.99/0.07 grounding split of [V-25](docs/validation-log.md) would all have been invented
incorrectly.

**Rejected alternative 4.** Screen recordings as the fallback, which need no code. Rejected
because a video cannot take a question. The value of the segment is submitting the prompt an
attendee asks about, and replay preserves that for any recorded prompt.

---

## 13. A measurement instrument that creates a guardrail outside Terraform

**Status:** accepted, narrowly

**Context.** Decision 5 makes `shared/scenario.json` the single policy definition and
Terraform its only writer. That decision stands. But the demo's headline claim — that the
default CLASSIC tier misses a Swahili prompt attack which STANDARD catches — could not be
measured, because `terraform apply` cannot create a guardrail in an account lacking
`bedrock:TagResource`: Terraform tags every resource it manages
([V-13](docs/validation-log.md)). The three tag permissions were never granted here, so the
STANDARD half of the tier gap sat unmeasured while the README asserted it.

`CreateGuardrail` itself requires no tagging. `lab doctor --probe-write` had already
established that creating an *untagged* guardrail succeeds in this account. So the blocker
was never "cannot create a STANDARD guardrail" — it was "cannot create one *with tags*",
which is a narrower thing than the validation log had recorded.

**Decision.** `scripts/measure-tier-gap.py` builds the guardrail from the same
`shared/scenario.json`, under either tier, omitting only the tags. It exists to measure and
is not a deployment path: the resource it creates is untagged, unmanaged by any state file,
and deleted by `--delete`. Terraform remains the only supported way to create the guardrail
this project deploys.

**Consequences.**
- The tier gap is now measured on both halves ([V-26](docs/validation-log.md)): the Swahili
  prompt 0/5 blocked at CLASSIC, 5/5 at STANDARD, on two guardrails differing only in tier.
- It produced a finding no amount of documentation review would have: at CLASSIC the prompt
  trips **no policy at all**, so the guardrail is not scoring it below a threshold — it is
  not classifying it. And the *other* tier-gap prompt, an attack embedded in code, blocks at
  both tiers despite AWS documenting code-element detection as a STANDARD addition.
- The script duplicates the policy-construction logic that `guardrail.tf` expresses in HCL.
  That is real duplication and a real risk: the two could drift. It is mitigated by both
  reading the same JSON, and bounded by the script having exactly one job.
- **Every document that cites these numbers names the script**, so nobody mistakes the
  measurement for the deployment path.

**Rejected alternative 1.** Wait for the tag permissions. Rejected because the claim was
already published as fact in the README while resting on documentation alone, and the wait
had no end date. An asserted headline claim is worse than a measured one obtained awkwardly.

**Rejected alternative 2.** Remove `default_tags` from the provider so Terraform stops
tagging. Rejected because it degrades the real deployment path — tags are how the deployed
stack is attributed and cost-tracked — to work around a local permission gap. Fixing
production for a measurement is the wrong direction.

**Rejected alternative 3.** Delete the tier-gap claim from the documentation instead of
measuring it. Rejected because it is the most useful five minutes in the session for a
Kenyan audience, and the one finding here least likely to be encountered elsewhere.

**Rejected alternative 4.** Have the script also *update* an existing Terraform-managed
guardrail's tier in place, avoiding a second resource. Rejected because it would mutate a
resource Terraform owns, guaranteeing state drift, and because `update_guardrail` has its own
silent-failure mode: omitting `inputAction`/`inputEnabled` disables PII evaluation while
still reporting the rule present ([V-19](docs/validation-log.md)).
