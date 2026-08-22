# AWS prerequisites

Start here. This document is the first step of the lab and of the deployed demo.

```bash
export AWS_REGION=eu-west-1          # or any Region where Bedrock Guardrails runs
export AWS_PROFILE=<your-profile>    # or configure credentials another way

python -m lab doctor                 # read-only: creates nothing
python -m lab doctor --probe-write   # also creates and deletes a test guardrail
```

`lab doctor` checks credentials, account type, guardrail permissions, tag
permissions, SDK version, guardrail-profile coverage for your Region, and model
access. For each failure it prints the exact fix — and it distinguishes the two
failures that look identical but need completely different action.

`--probe-write` is worth the extra minute. A read-only check cannot tell you whether
`CreateGuardrail` works, and it cannot detect the tagging gap below, which breaks
`terraform apply` while leaving every read-only check green.

---

## Any Region, any account type

Nothing here is specific to one Region or one account shape. The configuration
derives what it needs:

| You set | Everything else is derived |
|---|---|
| `aws_region` | guardrail profile, model ARNs, IAM resource ARNs, ARN partition |
| `bedrock_model_id` | which IAM statements are emitted, and on which ARNs |

Change `aws_region` and apply. There is no second file to edit.

Guardrail profiles by geography — assembled automatically from your Region, per the
[AWS coverage table](https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-cross-region-support.html):

| Geography | Profile | Source Regions |
|---|---|---|
| US | `us.guardrail.v1:0` | us-east-1, us-east-2, us-west-1, us-west-2 |
| EU | `eu.guardrail.v1:0` | eu-central-1, eu-west-1, eu-west-3, eu-north-1, eu-south-1, eu-south-2, il-central-1 |
| UK | `uk.guardrail.v1:0` | eu-west-2 |
| Canada | `ca.guardrail.v1:0` | ca-central-1 |
| Australia | `au.guardrail.v1:0` | ap-southeast-2 |
| APAC | `apac.guardrail.v1:0` | ap-south-1, ap-northeast-1/2, ap-southeast-1/3/4/5/7, ap-east-2, me-central-1 |
| GovCloud | `us-gov.guardrail.v1:0` | us-gov-east-1, us-gov-west-1 |

A guardrail profile is needed **only by the STANDARD tier**. In a Region without one,
apply with `-var guardrail_tier=CLASSIC` — the tier is a demo variable anyway, and the
runbook switches it deliberately.

---

## The one distinction that matters

Two failures look almost identical and need completely different fixes.

| What AWS says | What it means | Who fixes it |
|---|---|---|
| `no identity-based policy allows` | a permission you have not been granted | you, or your account admin |
| `explicit deny in a service control policy` | an **organisation boundary** | an admin of the *management* account |

A service control policy is a ceiling. **No IAM policy can raise it.** Attaching more
permissions changes nothing, and time spent trying is wasted.

**And the trap:** an absent IAM grant *hides* an SCP deny behind it. While IAM lacks a
permission, authorisation stops at the identity-policy check and never reaches the
resource an SCP denies — so you see `no identity-based policy allows` and conclude
there is no SCP. Add the grant, and the SCP deny appears, looking as though the grant
caused it.

We lost hours to exactly this. See [V-09, V-11 and V-12](validation-log.md).

**So: after adding any IAM permission, run `lab doctor` again.** A further block may
now be visible. `lab doctor` says so itself rather than letting you assume otherwise.

---

## Standalone account

If `lab doctor` reports `standalone account — no service control policies apply`, you
need only IAM. Attach the policy below to your user, role, or SSO permission set.

### The Lab_Path

The self-paced lab creates one guardrail and calls `ApplyGuardrail`. It never invokes a
foundation model, so **Bedrock model access is not a prerequisite**.

Replace `REGION` and `ACCOUNT`:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "GuardrailLifecycle",
      "Effect": "Allow",
      "Action": [
        "bedrock:CreateGuardrail",
        "bedrock:CreateGuardrailVersion",
        "bedrock:UpdateGuardrail",
        "bedrock:DeleteGuardrail",
        "bedrock:GetGuardrail",
        "bedrock:ListGuardrails"
      ],
      "Resource": [
        "arn:aws:bedrock:REGION:ACCOUNT:guardrail/*",
        "arn:aws:bedrock:REGION:ACCOUNT:guardrail-profile/*"
      ]
    },
    {
      "Sid": "GuardrailTags",
      "Effect": "Allow",
      "Action": [
        "bedrock:TagResource",
        "bedrock:UntagResource",
        "bedrock:ListTagsForResource"
      ],
      "Resource": "arn:aws:bedrock:REGION:ACCOUNT:guardrail/*"
    },
    {
      "Sid": "ApplyGuardrail",
      "Effect": "Allow",
      "Action": "bedrock:ApplyGuardrail",
      "Resource": [
        "arn:aws:bedrock:REGION:ACCOUNT:guardrail/*",
        "arn:aws:bedrock:*:ACCOUNT:guardrail-profile/*"
      ]
    }
  ]
}
```

Two details that are easy to get wrong:

**The guardrail-profile ARN in `GuardrailLifecycle`.** Creating a guardrail that names
a profile requires permission on the *profile* as well as the guardrail. AWS documents
this under
[Permissions to create and manage guardrails for cross-Region inference](https://docs.aws.amazon.com/bedrock/latest/userguide/guardrail-profiles-permissions.html).
CLASSIC-tier guardrails do not need it, but including it costs nothing and avoids a
confusing failure the first time someone tries STANDARD.

**The wildcard Region in `ApplyGuardrail`.** A guardrail profile routes requests to any
Region in its geography, and `ApplyGuardrail` must be permitted on the profile object
in **every destination**, not only your source Region. Pin it to one Region and calls
fail intermittently, naming a Region you never asked for. The EU profile has seven
destinations; APAC has thirteen.

**The tag statement is not optional.** Terraform tags every resource it manages and
reads tags back when refreshing state. Without it:

- `terraform apply` fails on `bedrock:TagResource`
- removing `default_tags` lets it apply **once**
- every later `terraform plan` then fails on `bedrock:ListTagsForResource`

The guardrail exists and is unmanageable, while every read-only check passes. Observed
as [V-13](validation-log.md); `lab doctor --probe-write` detects it by retrying an
untagged create.

### Adding the answer stage

Stage 2 invokes a model, and needs two things.

**First, enable the model.** Bedrock console in your Region → **Model access** →
**Anthropic Claude Haiku 4.5**. This is an account setting, separate from IAM, and the
single most common reason a first run fails.

**Second, grant `bedrock:InvokeModel`** — and the policy depends on which kind of
identifier you use. `terraform apply` builds the right one for you; this is what to
attach to *your own* role if you run the backend locally.

Current Claude models are not served on a bare model ID in most Regions, so you need an
inference profile. Two kinds exist and they need different IAM.

**A `global.` profile** — the default, because inference stays in your Region. AWS
requires a **three-part** policy and states that all three statements are needed:
remove one and the call is denied
([source](https://docs.aws.amazon.com/bedrock/latest/userguide/global-cross-region-inference.html)).

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "GlobalProfileInferenceProfile",
      "Effect": "Allow",
      "Action": "bedrock:InvokeModel",
      "Resource": "arn:aws:bedrock:REGION:ACCOUNT:inference-profile/global.anthropic.claude-haiku-4-5-20251001-v1:0",
      "Condition": { "StringEquals": { "aws:RequestedRegion": "REGION" } }
    },
    {
      "Sid": "GlobalProfileRegionalModel",
      "Effect": "Allow",
      "Action": "bedrock:InvokeModel",
      "Resource": "arn:aws:bedrock:REGION::foundation-model/anthropic.claude-haiku-4-5-20251001-v1:0",
      "Condition": {
        "StringEquals": {
          "aws:RequestedRegion": "REGION",
          "bedrock:InferenceProfileArn": "arn:aws:bedrock:REGION:ACCOUNT:inference-profile/global.anthropic.claude-haiku-4-5-20251001-v1:0"
        }
      }
    },
    {
      "Sid": "GlobalProfileGlobalModel",
      "Effect": "Allow",
      "Action": "bedrock:InvokeModel",
      "Resource": "arn:aws:bedrock:::foundation-model/anthropic.claude-haiku-4-5-20251001-v1:0",
      "Condition": {
        "StringEquals": {
          "aws:RequestedRegion": "unspecified",
          "bedrock:InferenceProfileArn": "arn:aws:bedrock:REGION:ACCOUNT:inference-profile/global.anthropic.claude-haiku-4-5-20251001-v1:0"
        }
      }
    }
  ]
}
```

The third statement's ARN — `arn:aws:bedrock:::foundation-model/...` — has **no Region
and no account**. That is intentional and required: it is what permits the cross-Region
routing. And note the condition value: for that call `aws:RequestedRegion` is the
literal string `unspecified`, not a Region name. An SCP written against Region names
will not match it, which is worth knowing before you ask an administrator to change one.

**A geographic profile** (`us.`, `eu.`, `apac.`, …) fans out across its geography and
picks a destination per request, so the foundation-model ARN needs a wildcard Region:

```json
{
  "Sid": "GeographicProfileInvokeModel",
  "Effect": "Allow",
  "Action": "bedrock:InvokeModel",
  "Resource": [
    "arn:aws:bedrock:*::foundation-model/anthropic.claude-haiku-4-5-20251001-v1:0",
    "arn:aws:bedrock:REGION:ACCOUNT:inference-profile/eu.anthropic.claude-haiku-4-5-20251001-v1:0"
  ]
}
```

**Both ARN forms are required in either case.** A profile resolves to a foundation
model, so `InvokeModel` must be permitted on the profile *and* the model beneath it.
Granting only one produces an `AccessDeniedException` that reads like a model-access
problem.

### The deployed stack

Beyond the guardrail, `terraform apply` creates a Lambda function, an HTTP API, an
Amplify app, an IAM role, two log groups and two alarms. `AdministratorAccess` is
simplest for a sandbox. For something narrower: `lambda:*`, `apigateway:*`, `amplify:*`,
`logs:*`, `cloudwatch:*`, plus `iam:CreateRole`, `iam:AttachRolePolicy`,
`iam:PutRolePolicy`, `iam:PassRole` and `iam:TagRole` scoped to the role the
configuration creates.

---

## Organisation member account

`lab doctor` reports `inside an AWS Organization`, or names the management account.
Everything above applies — **and an SCP can override all of it.**

### What to send your administrator

```
Account:  <your account id>
Region:   <your region>
Blocked:  bedrock:InvokeModel
SCP:      <the policy ARN lab doctor printed>

Please allow bedrock:InvokeModel on:
  arn:aws:bedrock:*::foundation-model/anthropic.claude-haiku-4-5-20251001-v1:0
  arn:aws:bedrock:::foundation-model/anthropic.claude-haiku-4-5-20251001-v1:0

Both ARN forms are needed. The second has no Region or account, which is how AWS
represents the global cross-Region routing path. An SCP condition written against
Region names will not match it — for that call aws:RequestedRegion is the literal
string "unspecified".
```

Ask which Regions the SCP permits. If it is a deliberate control on generative-model
use, that is a legitimate refusal — see *Working without a model*.

### SSO permission sets

If your credentials come from IAM Identity Center, the policy goes on the **permission
set**, not the role. Roles named `AWSReservedSSO_*` are managed by Identity Center and
your edits are overwritten.

1. Management account → IAM Identity Center → **Permission sets** → your set
2. **Inline policy** → paste the statements above
3. **Accounts** tab → select the account → **Provision permission set**

Step 3 is mandatory: changes do not reach the account until the set is re-provisioned.
Then:

```bash
aws sso logout
aws sso login --profile <your-profile>
```

Re-login matters. Your existing session token carries the old permissions.

### Which model profile to choose

Under an SCP, prefer `global.` The reason is worth stating: a profile that resolves to a
single Region cannot route a request into a Region your organisation denies. A
geographic profile chooses its own destination per request, so the same call can
succeed and fail on alternate attempts, and the error names a Region you never chose.

Pinning inference to one Region makes the failure attributable to your configuration
rather than to AWS's routing. See ADR decision 10 and [V-11](validation-log.md).

---

## Working without a model

If `lab doctor` ends with:

```
The guardrail permissions are in place; only model invocation is denied.
```

you can still run almost everything, because **two of the three pipeline stages never
invoke a model** — which is the demo's central argument, not a workaround.

| Stage | Needs a model | Works |
|---|---|---|
| Screen — `ApplyGuardrail(INPUT)` | no | **yes** |
| Answer — `Converse` | yes | falls back to a canned bulletin answer |
| Verify — `ApplyGuardrail(OUTPUT)` | no | **yes** |

- The **Lab_Path** is entirely unaffected. Requirement 1 restricts it to
  `ApplyGuardrail` precisely so model access is not a prerequisite.
- The **Conformance_Runner** skips model-dependent cases and reports them skipped, not
  failed.
- The **deployed demo** substitutes an answer drawn from Extension Bulletin 14, labels
  it in the Background_View, and reports `model_invoked: false`. Stages 1 and 3 stay
  live. Set `ANSWER_FALLBACK=false` to make a model failure a hard error instead.

---

## Deploying the stack needs IAM permissions the lab does not

The Lab_Path creates exactly one AWS resource and needs no IAM write permission at all. The
**deployed** stack needs a Lambda execution role, and that is a separate grant:

```bash
python -m lab doctor --check-deploy     # creates and deletes one throwaway IAM role
```

Without `iam:CreateRole` there is no execution role, therefore no Lambda, therefore no
endpoint — which is why deployed SDK parity and deployed latency went unmeasured in this
repository ([V-29](validation-log.md), [V-30](validation-log.md)). Unlike an SCP, this is a
grant an administrator can add.

`--check-deploy` is opt-in because the lab does not need it, and a failure that does not
affect your path would only be noise. It is the one probe in `lab doctor` that creates
anything: a trust-policy-only role with no attached policies, deleted immediately, with the
deletion verified rather than assumed.

Once granted, everything for the deployed measurements is already written:

```bash
./scripts/deploy-and-validate.sh        # deploy, probe SDK parity, time it, tear down
```

That script decides for itself whether the SDK needs pinning into the bundle — it only does
so if the deployed runtime actually rejects a field, because shipping our boto3 takes the
bundle from 9.0M to 37M.

---

## Other prerequisites `lab doctor` checks

**boto3 ≥ 1.38.0.** Two different fields set this floor, and they fail in opposite ways.

`outputScope` on the `ApplyGuardrail` **request** arrives in 1.37.0; both the screen and
verify stages pass it, so on anything earlier every call fails before reaching AWS with
`Unknown parameter in input: "outputScope"` (bisected — [V-14](validation-log.md):
1.36.26 lacks it).

`tier` on the `GetGuardrail` **response** arrives in 1.38.0. On 1.37.x AWS sends the tier
and botocore discards it, because the bundled service model does not declare the field.
Nothing raises — the value is simply `None`, indistinguishable from a guardrail with no
tier set, and the lab labelled a CLASSIC measurement as STANDARD for it (bisected —
[V-24](validation-log.md)).

A rejected request field is loud. A dropped response field is silent, which is why the
floor is 1.38.0 rather than 1.37.0.

**A guardrail must have at least one policy.** `CreateGuardrail` with no policy returns
`ValidationException`, not `AccessDeniedException` — easy to misread as a permission
problem. `lab doctor` classifies it correctly.

**Topic definitions are capped at 200 characters.** Not documented by AWS; bisected in
[V-16](validation-log.md). The committed `Agrochemical Dosing` definition is 152
characters, leaving 48 for the tuning exercise.
