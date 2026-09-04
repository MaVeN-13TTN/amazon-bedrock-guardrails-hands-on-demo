# Running the demo

Two paths. **Local** needs an AWS account and a guardrail; **deployed** stands up
the whole stack in eu-west-1 with one `terraform apply`.

> ### Status: Path A has never been applied against AWS
>
> Read this before choosing a path. **No Lambda, API Gateway or Amplify app created
> by this repository has ever existed.** `iam:CreateRole` is denied in the account
> this project was built in, so `terraform apply` cannot create the Lambda execution
> role, and every resource downstream of it is unreached
> ([V-29](docs/validation-log.md)). Being honest about that is worth more than a
> confident instruction that fails on someone else's laptop.
>
> **If you want a path that is known to work, use [the lab](docs/lab-guide.md).** It
> creates one guardrail, needs no model access, and every one of its 15 checkpoints
> has been met against live AWS ([V-20](docs/validation-log.md)).
>
> What *is* verified for Path A, with no AWS involved:
>
> | | How |
> |---|---|
> | Terraform parses, validates and is canonically formatted | `terraform validate`, `fmt -check` in `verify-install.sh` |
> | The Lambda bundle builds, at the right architecture | `scripts/package-backend.sh` → 9.0M, `aarch64` wheels |
> | The Lambda entry point routes and answers | `backend/tests/test_lambda_handler.py` — a synthetic API Gateway v2 event through Mangum |
> | The frontend builds as a static export | `npm run build` → 4 pages exported |
> | The whole pipeline runs with no credentials | `scripts/replay-check.sh` |
>
> What is **not** verified: IAM in a real account, API Gateway's event shape, CORS
> against a live Amplify origin, cold-start latency, and whether `apply` completes.
>
> **If you are the first to run it, please [open an issue](https://github.com/MaVeN-13TTN/amazon-bedrock-guardrails-hands-on-demo/issues)
> with what broke.** Run `python -m lab doctor --check-deploy` first — it tells you
> whether your account has `iam:CreateRole` before you spend time on it.

- [Prerequisites](#prerequisites)
- [Path A — deploy everything](#path-a--deploy-everything)
- [Path B — local development](#path-b--local-development)
- [Switching guardrail tier live](#switching-guardrail-tier-live)
- [Verifying it works](#verifying-it-works)
- [Troubleshooting](#troubleshooting)
- [Tearing down](#tearing-down)

---

## Prerequisites

| Tool | Version | Why |
|---|---|---|
| AWS CLI | v2 | credentials, Amplify deploy |
| Terraform | ≥ 1.7 | infrastructure |
| Python | 3.12 | backend, and the Lambda bundle targets 3.12 |
| Node.js | ≥ 20 | Next.js 15 |
| `jq`, `zip`, `curl` | any | deploy and smoke-test scripts |

### 1. Credentials

```bash
aws configure          # or export AWS_PROFILE=...
export AWS_REGION=eu-west-1
aws sts get-caller-identity     # must succeed before anything else
```

### 2. Bedrock model access — do this first

Model access is per-account, per-Region, and is the single most common reason a
first run fails. In the **Bedrock console, eu-west-1** → *Model access* → enable
**Anthropic Claude Haiku 4.5**, and wait for `Access granted`.

Then confirm the model actually answers. In eu-west-1 an inference-profile prefix
is load-bearing — a bare model ID is rejected:

```bash
aws bedrock-runtime converse \
  --region eu-west-1 \
  --model-id global.anthropic.claude-haiku-4-5-20251001-v1:0 \
  --messages '[{"role":"user","content":[{"text":"Say OK."}]}]' \
  --inference-config '{"maxTokens":10}'
```

If that returns text, you are ready. If it fails, see
[Troubleshooting](#troubleshooting) — do not proceed, because everything else
depends on it.

**Why `global.` and not `eu.`** Both profiles are ACTIVE in eu-west-1, and both
satisfy the "not a bare model ID" requirement. They differ in where inference runs:
`eu.` fans out across six EU Regions and picks one per request, while `global.`
resolves to eu-west-1 only. If your account sits under an organisation SCP that
restricts Bedrock by Region, the `eu.` profile can route into a denied Region and
fail with an `AccessDeniedException` naming a Region you never asked for. That is
not a misconfiguration on your side and no IAM change fixes it. `global.` keeps the
Region predictable. See [ADR decision 10](ADR.md) and validation log entries V-09
and V-11.

### 3. Confirm the cross-Region guardrail profile

The STANDARD tier needs one; CLASSIC needs none. The profile is **derived from your
Region** in [`infrastructure/regions.tf`](infrastructure/regions.tf) — `eu-west-1`
resolves to `eu.guardrail.v1:0` — so there is normally nothing to set.

**There is no CLI command that lists guardrail profiles.** `aws bedrock
list-guardrail-profiles` does not exist in aws-cli 2.36.14, and
`list-inference-profiles` returns no guardrail profile either, so the identifier
cannot be confirmed from the CLI ([V-01](docs/validation-log.md)). The mapping in
`regions.tf` comes from [AWS's coverage
table](https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-cross-region-support.html)
instead.

If your Region has no profile, `terraform apply` fails a precondition with a readable
message rather than an AWS rejection. Either use CLASSIC, which needs no profile:

```bash
terraform apply -var guardrail_tier=CLASSIC
```

or set the identifier explicitly if AWS has since added one for your Region:

```bash
terraform apply -var guardrail_profile_id=<geo>.guardrail.v1:0
```

Do not put `guardrail_profile_id` in `terraform.tfvars` as a matter of course —
hardcoding it is what breaks a later Region change.

---

## Verify your install first

```bash
./scripts/verify-install.sh              # no AWS account needed
./scripts/verify-install.sh --with-aws   # also runs lab doctor
python -m lab doctor --check-deploy      # deployment permissions specifically
```

The last one matters here: deploying needs `iam:CreateRole` for the Lambda execution role,
which the Lab_Path does not. Without it `terraform apply` fails and no endpoint exists
([V-29](docs/validation-log.md)).

---

## Path A — deploy everything

```bash
git clone https://github.com/MaVeN-13TTN/amazon-bedrock-guardrails-hands-on-demo.git
cd amazon-bedrock-guardrails-hands-on-demo

cd infrastructure
cp terraform.tfvars.example terraform.tfvars     # defaults are fine
terraform init
terraform apply
```

`apply` builds the Lambda bundle for you (see ADR decision 8) and creates the
guardrail, Lambda, HTTP API, Amplify app, IAM role, log groups and alarms.
Expect 2–4 minutes.

Then deploy the frontend and check it:

```bash
cd ..
./scripts/deploy-frontend.sh     # builds Next.js, pushes the bundle to Amplify
./scripts/smoke-test.sh          # exercises the API end to end
```

`deploy-frontend.sh` reads the API URL from Terraform and bakes it into the build,
so there is nothing to configure by hand.

Useful outputs:

```bash
cd infrastructure
terraform output frontend_url        # the demo
terraform output api_base_url        # the API
terraform output guardrail_id        # for local development
terraform output -raw local_env_file # paste straight into backend/.env
```

The first Amplify deploy takes about a minute to go live after the script exits.

> **Before presenting:** send one warm-up request so the audience does not watch a
> cold start. `curl "$(terraform output -raw api_base_url)/health"`

---

## Path B — local development

Run the backend and frontend on your machine against a **real guardrail** — there
is no offline mode, because the whole demo is what Bedrock returns.

### Get a guardrail

Either apply the Terraform (Path A) and reuse its guardrail, or apply just that
one resource:

```bash
cd infrastructure
terraform init
terraform apply -target=aws_bedrock_guardrail.main -target=aws_bedrock_guardrail_version.main
terraform output -raw local_env_file > ../backend/.env
```

### Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt

cat .env          # check GUARDRAIL_ID is populated
uvicorn app.main:app --reload --port 8000
```

- API: <http://localhost:8000>
- Interactive docs: <http://localhost:8000/docs>
- Health: <http://localhost:8000/health> — `"status":"ok"` means a guardrail is attached

Tests need no AWS credentials; Bedrock is stubbed:

```bash
pytest -q
ruff check .
```

### Frontend

```bash
cd frontend
npm install
cp .env.example .env.local        # defaults to http://localhost:8000
npm run dev
```

Open <http://localhost:3000>. To point a local frontend at the *deployed* API,
put the `api_base_url` output in `.env.local` instead.

---

## Switching guardrail tier live

The tier gap is the most useful five minutes in the talk, and it is a variable:

```bash
cd infrastructure
terraform apply -var guardrail_tier=CLASSIC -auto-approve
```

Send the Swahili prompt attack from the UI's *tier gap* chip — nothing fires.
CLASSIC covers English, French and Spanish only. Then:

```bash
terraform apply -var guardrail_tier=STANDARD -auto-approve
```

Same prompt, now blocked — **if** the application is reading the tier you just applied.
That depends on one setting, and getting it wrong makes the segment prove nothing.

### What a tier change does and does not alter

| | `publish_guardrail_version = false` | `publish_guardrail_version = true` (the committed default) |
|---|---|---|
| Guardrail version the app reads | `DRAFT` — moves with every apply | a **pinned number** — does not move |
| Does the app see the new tier? | **yes, immediately** | **no** — until a new version is cut |
| Lambda redeploy needed? | no | no, but the pinned version must be recut |
| Frontend rebuild needed? | no | no |

**The trap.** With a numbered version pinned and not recut after a tier change, the
application keeps evaluating against the previous tier. The same prompt produces the same
result, and the audience is shown a non-difference presented as a difference.

For a presented session, set:

```hcl
publish_guardrail_version = false
```

so `GUARDRAIL_VERSION` resolves to `DRAFT` and a tier change takes effect at once.

**Pre-swap check:** the Background_View header shows the guardrail version the running
application is using. **Confirm it reads `DRAFT` before you swap.** If it shows a number,
the swap will change nothing visible.

> Rehearse both applies before presenting. If `CLASSIC` is left in place at the
> end of the session, re-apply `STANDARD` so the repo matches its README.

### What was measured

**Both halves are measured** ([V-26](docs/validation-log.md)). Same policy, two guardrails
differing only in tier, 5 repetitions per prompt:

| Prompt | CLASSIC | STANDARD |
|---|---|---|
| Swahili prompt attack | **0/5** blocked | **5/5** blocked |
| Code-embedded attack | **5/5** blocked | **5/5** blocked |

Across the whole 36-case suite: false positives are **identical** at 10/70 (14.3%) on both
tiers, while true positives rise from **92.9%** at CLASSIC to **100%** at STANDARD. STANDARD
costs nothing in over-blocking on this set and gains 7.1 points of recall.

**Two caveats to carry onto the stage.** The Swahili result is the one to demonstrate — at
CLASSIC the guardrail does not classify that text *at all*, tripping no policy rather than
scoring below a threshold. The code-embedded prompt blocks at both tiers, so it does **not**
demonstrate the gap despite AWS documenting code-element detection as a STANDARD addition.

**Terraform still cannot create a STANDARD guardrail here.** The measurement used
`scripts/measure-tier-gap.py`, which builds the same policy untagged, because the three tag
permissions of [V-13](docs/validation-log.md) are absent. If your account has them,
`terraform apply -var guardrail_tier=STANDARD` is the supported path and the script is
unnecessary.

---

## Validating a deployment

Once the stack is up, three measurements need it — and one script runs them in order:

```bash
./scripts/deploy-and-validate.sh                  # deploy, validate, leave running
./scripts/deploy-and-validate.sh --wait-cold      # idle 15 min for a true cold sample
./scripts/deploy-and-validate.sh --destroy-after   # tear down when finished
```

It does three things worth knowing about:

**SDK parity.** `GET /api/diagnostics/sdk` is read from the deployed endpoint and from the
same code locally, and the two are printed side by side. The deployed Lambda uses the
runtime's boto3, because packaging strips ours — so the field sets can differ, and they fail
in opposite ways: a rejected *request* field raises loudly, while an unmodelled *response*
field is dropped silently ([V-14](docs/validation-log.md),
[V-24](docs/validation-log.md)).

**Pinning the SDK, only if warranted.** If the deployed runtime rejects a field, the script
rebuilds with `./scripts/package-backend.sh --pin-sdk` and redeploys. Otherwise it records
that no change was needed. That gate is deliberate: shipping our boto3 takes the bundle from
**9.0M to 37M** and slows cold starts, and the runtime's SDK is usually newer than the pin.

**Latency, sampled honestly.** One cold request and three warm ones at least 5 seconds apart,
**each reported individually** rather than averaged — a cold start is a different event from a
slow warm request, and one mean describes neither. Without `--wait-cold` the script says
plainly that the first sample is only cold if the endpoint was already idle.

```bash
python -m lab latency --api-base "$(terraform -chdir=infrastructure output -raw api_base_url)"
```

---

## Replay_Mode — running with no AWS

Every stage can be served from fixtures recorded against live AWS. This exists for the
presented session: a credential expiry or an organisation boundary discovered five minutes
before you go live should not end the demo.

Record once, while AWS works:

```bash
python -m lab conformance --record       # writes backend/app/fixtures/replay/
```

Then enable it:

```bash
export REPLAY_MODE=true                  # or REPLAY_MODE=true in backend/.env
```

**No boto3 client is constructed under replay** — not a stub, none at all. The pipeline
completes with no credentials, no Region and no network, which is verifiable:

```bash
./scripts/replay-check.sh                # unsets every AWS variable, then exercises all paths
```

Three things worth knowing:

- **Every replayed stage carries its provenance** — capture date, Region, tier and guardrail
  version. The Background_View shows them, so a recorded result is never displayed as though
  it were live.
- **The indicator sits outside the Chat_Window**, in the amber bar above it. A "recorded"
  label inside an assistant turn would show the audience something no real member would ever
  see, which would undo what the member view exists to demonstrate.
- **An unrecorded prompt returns 409**, listing the prompts that were recorded. That is not a
  failure — nothing is broken, the prompt simply was not captured.

Fixture files are named `<set>-<tier>.json`, so recording under the other tier adds rather
than overwrites. The tier-gap prompt needs both halves to exist at once.

| Variable | Default | What it does |
|---|---|---|
| `REPLAY_MODE` | `false` | serve every stage from fixtures; construct no client |
| `REPLAY_DIR` | `backend/app/fixtures/replay` | where fixtures are read from |
| `GUARDRAIL_TIER` | `CLASSIC` | which tier's fixtures to prefer where a prompt has both |

---

## Verifying it works
`./scripts/smoke-test.sh` checks, against the deployed API:

| Check | Expectation |
|---|---|
| `/health` | `status: ok` |
| `/api/context` | names Murang'a County |
| in-scope question | runs all three stages, `stopped_at: null` |
| dosing question | `stopped_at: screen`, names `Agrochemical Dosing` |
| PII prompt | `ANONYMIZED`, not blocked |
| grounded answer | passes |
| ungrounded answer | intervenes |

It also runs against a local backend: `./scripts/smoke-test.sh http://localhost:8000`.

Logs:

```bash
aws logs tail "$(terraform -chdir=infrastructure output -raw lambda_log_group)" --follow
```

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `AccessDeniedException` on converse | model access not granted in eu-west-1 | Bedrock console → Model access → enable Claude Haiku 4.5, wait for `Access granted` |
| `Invocation with on-demand throughput isn't supported` | bare model ID — most Regions reject one | use an inference profile; the default `bedrock_model_id` is already `global.anthropic.claude-haiku-4-5-...` ([V-08](docs/validation-log.md)) |
| `ValidationException` mentioning `guardrailProfile` | STANDARD tier without a valid profile for your Region | `terraform apply -var guardrail_tier=CLASSIC`, which needs no profile; or set `-var guardrail_profile_id=<geo>.guardrail.v1:0`. No CLI command lists these ([V-01](docs/validation-log.md)) — see [step 3](#3-confirm-the-cross-region-guardrail-profile) |
| `An argument named "tier_config" is not expected` | AWS provider 5.x | provider must be `~> 6.0`; `rm -rf .terraform .terraform.lock.hcl && terraform init` |
| `503 No guardrail configured` from the API | `GUARDRAIL_ID` empty | local: refresh `backend/.env` from `terraform output -raw local_env_file`. deployed: re-apply |
| `ImportModuleError: _pydantic_core` in Lambda | wrong-architecture wheels | re-run `./scripts/package-backend.sh`; it forces `manylinux2014_aarch64` |
| Frontend loads but every call fails CORS | Amplify URL not in the allow-list | re-`apply` (the URL is derived from the app id), or add it to `extra_cors_origins` |
| Frontend shows `no guardrail configured` | frontend built against the wrong API | re-run `./scripts/deploy-frontend.sh`; the URL is baked in at build time |
| First request takes ~3 s | Lambda cold start | send a warm-up request before presenting |
| Grounding never intervenes | thresholds too permissive | raise `grounding_threshold` in `shared/scenario.json`, re-apply |

Diagnostic order when something is wrong: `sts get-caller-identity` →
`bedrock-runtime converse` → `/health` → `smoke-test.sh`. Each step depends on the
one before it, so fix them in that order.

---

## Tearing down

```bash
cd infrastructure
terraform destroy
```

That removes everything Terraform created: the guardrail and its versions, the Lambda
function, the API Gateway HTTP API, the Amplify application, the IAM role and its
policies, both CloudWatch log groups and both metric alarms.

**If it fails with `AccessDeniedException` on `bedrock:ListTagsForResource`**, you are in an
account without the three tag permissions. The failure is in the *refresh* phase, before
anything is deleted, so nothing has happened yet — and the delete itself needs no tag
permission ([V-28](docs/validation-log.md)):

```bash
terraform destroy -auto-approve -refresh=false      # skips the tag read
python -m lab teardown                              # or: finds it by name, reads no state
```

Without those permissions Terraform can create the guardrail once and then neither re-plan
nor destroy it, which is worth knowing before you apply rather than after.

**Verify each one is gone** rather than trusting the exit status:

```bash
aws bedrock list-guardrails --region $AWS_REGION --query 'length(guardrails)'
aws lambda list-functions --region $AWS_REGION --query "length(Functions[?starts_with(FunctionName,'kilimo-desk')])"
aws apigatewayv2 get-apis --region $AWS_REGION --query "length(Items[?starts_with(Name,'kilimo-desk')])"
aws amplify list-apps --region $AWS_REGION --query "length(apps[?starts_with(name,'kilimo-desk')])"
aws logs describe-log-groups --region $AWS_REGION --log-group-name-prefix /aws/lambda/kilimo-desk --query 'length(logGroups)'
aws cloudwatch describe-alarms --region $AWS_REGION --alarm-name-prefix kilimo-desk --query 'length(MetricAlarms)'
```

All six should return `0`.

**What persists, and costs nothing:**

- **Bedrock model access** — an account setting, not a resource. No charge while unused.
- **IAM permissions** you added to your own role or permission set. No charge.

### If the Terraform state is lost

If you deleted the directory, or `terraform destroy` cannot find the resources, remove
them by name. The guardrail has a purpose-built command that reads no state:

```bash
python -m lab teardown          # finds the guardrail by name, deletes it, verifies
```

For the rest:

```bash
# List, then delete each by name
aws lambda list-functions --region $AWS_REGION --query "Functions[?starts_with(FunctionName,'kilimo-desk')].FunctionName" --output text
aws lambda delete-function --function-name kilimo-desk-api --region $AWS_REGION

aws apigatewayv2 get-apis --region $AWS_REGION --query "Items[?starts_with(Name,'kilimo-desk')].ApiId" --output text
aws apigatewayv2 delete-api --api-id <id> --region $AWS_REGION

aws amplify list-apps --region $AWS_REGION --query "apps[?starts_with(name,'kilimo-desk')].appId" --output text
aws amplify delete-app --app-id <id> --region $AWS_REGION

aws iam list-attached-role-policies --role-name kilimo-desk-lambda
aws iam detach-role-policy --role-name kilimo-desk-lambda --policy-arn <arn>
aws iam delete-role-policy --role-name kilimo-desk-lambda --policy-name kilimo-desk-bedrock
aws iam delete-role --role-name kilimo-desk-lambda

aws logs delete-log-group --log-group-name /aws/lambda/kilimo-desk-api --region $AWS_REGION
aws cloudwatch delete-alarms --alarm-names kilimo-desk-api-errors kilimo-desk-api-throttles --region $AWS_REGION
```

Only the guardrail carries an ongoing charge, and only when evaluations are made — see
[cost.md](docs/cost.md).

If you leave the stack running, put a **budget alarm** on the account. The API is
unauthenticated by design for this demo — see ADR decision 6.
