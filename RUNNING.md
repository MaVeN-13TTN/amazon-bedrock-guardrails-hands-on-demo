# Running the demo

Two paths. **Local** needs an AWS account and a guardrail; **deployed** stands up
the whole stack in eu-west-1 with one `terraform apply`.

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

Then confirm the model actually answers. In eu-west-1 the `eu.` prefix is
load-bearing — a bare model ID is rejected:

```bash
aws bedrock-runtime converse \
  --region eu-west-1 \
  --model-id eu.anthropic.claude-haiku-4-5-20251001-v1:0 \
  --messages '[{"role":"user","content":[{"text":"Say OK."}]}]' \
  --inference-config '{"maxTokens":10}'
```

If that returns text, you are ready. If it fails, see
[Troubleshooting](#troubleshooting) — do not proceed, because everything else
depends on it.

### 3. Confirm the cross-Region guardrail profile

The STANDARD tier needs one. The default is `eu.guardrail.v1:0`; verify:

```bash
aws bedrock list-guardrail-profiles --region eu-west-1
```

If the profile differs, set `guardrail_profile_id` in `terraform.tfvars`.

---

## Path A — deploy everything

```bash
git clone <this repo> && cd amazon-bedrock-guardrails-hands-on-demo

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

Same prompt, now blocked. Each apply takes a few seconds and needs no redeploy of
Lambda or frontend — the guardrail is referenced by id, not by value.

> Rehearse both applies before presenting. If `CLASSIC` is left in place at the
> end of the session, re-apply `STANDARD` so the repo matches its README.

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
| `Invocation with on-demand throughput isn't supported` | bare model ID in eu-west-1 | use the `eu.` inference profile — the default `bedrock_model_id` already does |
| `ValidationException` mentioning `guardrailProfile` | STANDARD tier without a valid profile | `aws bedrock list-guardrail-profiles --region eu-west-1`, then set `guardrail_profile_id`; or apply with `-var guardrail_tier=CLASSIC` |
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

That removes everything, including log groups and the guardrail. Nothing is
created outside Terraform, so there is no manual cleanup — with two caveats:

- **Bedrock model access** stays enabled on the account. It costs nothing.
- **Amplify deployment artifacts** are deleted with the app.

If you leave the stack running, put a **budget alarm** on the account. The API is
unauthenticated by design for this demo — see ADR decision 6.
