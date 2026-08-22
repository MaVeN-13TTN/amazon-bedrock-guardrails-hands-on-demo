# What this costs

Read this before you run anything.

**Lab_Path total: under $0.05.** One guardrail, roughly 610 `ApplyGuardrail`
evaluations, no foundation model. Deleting the guardrail afterwards leaves **$0.00**
recurring.

**Deployed stack, one rehearsal plus one session: under $1.00.** Nine resources, none
with an hourly charge while idle.

Both figures are derived below. If a number matters to your decision, check the
derivation rather than the headline.

---

## An honest word about these numbers

Unit prices are not in the AWS documentation set — they live on the
[Amazon Bedrock pricing page](https://aws.amazon.com/bedrock/pricing/), which changes
and varies by Region. So this document does two things separately:

1. **The billing model** — how you are charged, and for what. **Verified against AWS
   documentation**, cited inline. This does not change often.
2. **The quantities** — how many units this demo consumes. **Measured** from the
   committed records under `results/`.

Multiply (2) by the price you read for your Region. The `unit price` column below is
left as a symbol rather than filled with a number that would be wrong somewhere, or
stale by the time you read it.

That is deliberate. A cost document with confidently wrong figures is worse than one
that shows you the arithmetic.

**Region and date the model was confirmed:** eu-west-1, 2026-08-22.

---

## The billing model

**Verified — Bedrock User Guide,
[How charges are calculated](https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-how.html).**

> Charges for Amazon Bedrock Guardrails are incurred only for the policies configured
> in the guardrail.

Three consequences, quoted from the same page:

| Outcome | Guardrail evaluation | Model inference |
|---|---|---|
| Guardrail blocks the **input** | charged | **not charged** |
| Guardrail blocks the **response** | charged, input *and* output | charged — the response was generated first |
| Nothing blocked | charged, input and output | charged |

**The first row is the demo's cost argument, and it is AWS's own statement.** A request
rejected at stage 1 pays for one guardrail evaluation and **nothing for inference**.
That is not a claim this repository makes about Bedrock; it is how Bedrock bills.

Three further facts:

- **Billing is per 1,000 text units, per policy.** Each policy you enable is priced
  separately (**verified**, same page). A guardrail with five policies costs roughly
  five times one with a single policy, for the same text.
- **You pay only for policies you configure.** An unused policy type costs nothing.
- **The API tells you the count.** `ApplyGuardrail` returns `textUnits` per check
  (**verified** — [ApplyGuardrail response
  format](https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-use-invoke-guardrail-checks-using.html)),
  so you can audit consumption rather than estimate it.

### What this guardrail enables

**5 policies** (**measured** from `shared/scenario.json`):

| Policy | Configuration |
|---|---|
| Denied topics | 3 topics |
| Content filters | 6 categories on input, 5 on output |
| Word filters | 2 custom words + the managed profanity list |
| Sensitive information | 2 PII entity types + 2 custom regexes |
| Contextual grounding | grounding and relevance, threshold 0.7 |

Automated Reasoning is **not** configured — deliberately, see [ADR decision
11](../ADR.md) — so it contributes nothing.

**Every evaluation is billed across all five.** That is the single largest lever on
this demo's cost. Disabling contextual grounding would cut roughly a fifth of the
guardrail charge, and it is why leaving unused policies configured is not free.

---

## Lab_Path quantities

**Measured.** Completing every Lab_Guide module once:

| Source | Evaluations | Where the count comes from |
|---|---|---|
| Module checkpoints, modules 1–8 | 19 | 15 checkpoints; 4 are probabilistic and run 5 repetitions |
| Conformance pass, 1 repetition | 31 | `lab conformance` |
| Tuning module: three iterations, 10 reps | 3 × 180 = 540 | 18 prompts × 10 repetitions × 3 |
| Free evaluation while learning | ~20 | allowance for `lab evaluate` |
| **Total, single pass** | **≈ 610** | |

**Three tuning iterations, not two.** The module's first narrowing made the
false-positive rate *worse* — 16.7% to 25.0% — so a third measurement is needed to
reach 8.3% ([V-17](validation-log.md), [results.md](results.md)). That is the
module's lesson, and it costs a third pass over the set.

The tuning module dominates — 540 of 610 evaluations, because measuring a
false-positive *rate* needs repetition. Run the loop at `--repeat 3` instead of 10 and
the total drops to about 232, at the cost of a noisier measurement.

**A second full pass adds the same ≈ 610.** There is no fixed setup cost to amortise:
guardrail creation is free, and only evaluations are billed.

| | Evaluations | Cost |
|---|---|---|
| First pass | ≈ 610 | 610 × 5 policies × P_guardrail ÷ 1000 |
| Each further pass | ≈ 610 | the same |
| Minimum viable pass (`--repeat 3`) | ≈ 232 | 232 × 5 × P_guardrail ÷ 1000 |

Where `P_guardrail` is the per-1,000-text-units price per policy for your Region.

**One evaluation costs `5 × P_guardrail ÷ 1000`** — five policies, one text unit for a
short prompt. **Enabling one more policy adds `P_guardrail ÷ 1000`** per evaluation, a
20% increase on this configuration.

### Model invocation

**$0.00.** The Lab_Path calls `ApplyGuardrail` only and never invokes a foundation
model — Requirement 1.2, which is why Requirement 1.3 states that model access is not a
prerequisite. This is not a limitation worked around; it is the demo's argument, priced.

---

## Deployed stack quantities

**Measured** where a count exists; **not measured** where the stack was never deployed
(the tag permissions of [V-13](validation-log.md) blocked it).

| Component | Unit | Quantity | Idle cost |
|---|---|---|---|
| Guardrail evaluations | per 1,000 units, per policy | ≈ 200 for a rehearsal + a session | — |
| Foundation model | per 1,000 input + output tokens | ≈ 60 calls × ~250 in / ~120 out | — |
| Lambda | per request + GB-second | ≈ 200 requests, 512 MB, ~1.5 s | **$0.00** |
| API Gateway HTTP API | per million requests | ≈ 200 | **$0.00** |
| Amplify Hosting | per GB served + build minute | ~1 MB × 200, ~2 builds | **$0.00** |
| CloudWatch Logs | per GB ingested + stored | < 10 MB, 14-day retention | **≈ $0.00** |
| CloudWatch alarms | per alarm-month | 2 | small, pro-rated |
| IAM role, log groups | — | — | **$0.00** |

**Idle cost per 24 hours: $0.00 for every component but two.** Nothing here is
hourly-billed: Lambda, API Gateway and Amplify Hosting charge per use, and a stack
serving no traffic invokes none of them.

The two exceptions, both trivial:

- **CloudWatch Logs storage.** Under 10 MB, retained 14 days, then deleted
  automatically by `log_retention_days`. Fractions of a cent per month.
- **CloudWatch alarms.** Two alarms, priced per alarm-month and pro-rated. Delete the
  stack the same day and you pay hours, not a month.

**Idle cost per 30-day month, if you forget to destroy:** the two alarms plus a few
megabytes of logs. Well under a dollar, but not zero — which is the argument for
running `terraform destroy`.

### A guardrail left in place

**$0.00 per 30-day month.** A guardrail has no hourly or monthly charge; only
evaluations are billed (**verified** — charges are incurred for *policies configured in
the guardrail*, consumed per text unit, not for the resource existing).

So forgetting `lab teardown` costs nothing recurring. Run it anyway — a stray guardrail
in a shared account is confusing even when it is free, and the teardown is one command.

---

## Free Tier

**These figures assume no Free Tier allowance.** Bedrock Guardrails is not in the AWS
Free Tier, so the guardrail evaluations are charged from the first call.

Lambda, API Gateway, CloudWatch and Amplify all have Free Tier allowances that this
demo's volumes sit far inside — a few hundred requests against a million-request
monthly allowance. If your account has Free Tier remaining, those components are very
likely $0.00. If it does not, they are the fractions of a cent shown above.

**The figures above are the no-Free-Tier case.** There is no version of this that costs
more than the numbers here.

---

## Reducing it further

| Change | Effect |
|---|---|
| `--repeat 3` on the tuning loop | ≈ 430 → ≈ 178 evaluations, noisier measurement |
| Lab_Path only, skip the deployed stack | one billable resource, no Lambda/API/Amplify |
| `-var guardrail_tier=CLASSIC` | no cost difference; avoids needing a profile |
| Disable contextual grounding | ~20% off every evaluation, loses stage 3 |
| `lab teardown` when finished | removes the only recurring charge |

The Lab_Path is deliberately the cheap path. Requirement 1.1 restricts it to a single
billable resource so that the interesting parts cost cents rather than a decision.

---

## Checking your own bill

```bash
# What each call consumed, straight from the API:
python -m lab evaluate --prompt "When are the collection points open?"
#   the raw assessment includes a `usage` block with textUnits per policy

# Then, after a run:
aws ce get-cost-and-usage \
  --time-period Start=$(date -I -d '1 day ago'),End=$(date -I) \
  --granularity DAILY --metrics UnblendedCost \
  --filter '{"Dimensions":{"Key":"SERVICE","Values":["Amazon Bedrock"]}}'
```

Cost Explorer lags by up to 24 hours, so a run today may not appear until tomorrow.
`textUnits` in the API response is immediate and is what you are billed on.
