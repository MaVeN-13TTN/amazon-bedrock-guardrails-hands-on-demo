#!/usr/bin/env bash
# Deploy the stack, then run the three validations that need a deployed endpoint.
#
#   26 · SDK parity     — what the runtime's boto3 accepts, versus the local pin
#   27 · pin the SDK    — only if 26 shows the runtime rejecting a field
#   28 · latency        — one cold sample, three warm, recorded individually
#
# Task 27 is deliberately conditional. Shipping our pinned boto3 takes the bundle
# from 9.0M to 37M (4.1x, measured) and slows cold starts, so it is only correct
# when the runtime's own SDK is too old for a field this code sends. The usual
# finding is that no change is needed, and that finding is worth recording.
#
# Prerequisites this script does not create for you:
#   iam:CreateRole, iam:PassRole   — for the Lambda execution role
#   bedrock:TagResource, UntagResource, ListTagsForResource  — Terraform tags
# Run `python -m lab doctor --probe-write` first; it names anything missing.
#
# Usage:
#   deploy-and-validate.sh                    deploy, validate, leave running
#   deploy-and-validate.sh --wait-cold        idle 15 min for a genuine cold sample
#   deploy-and-validate.sh --destroy-after    tear down when finished
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

WAIT_COLD=false
DESTROY_AFTER=false
for arg in "$@"; do
  case "$arg" in
    --wait-cold)     WAIT_COLD=true ;;
    --destroy-after) DESTROY_AFTER=true ;;
    -h|--help) sed -n '2,21p' "${BASH_SOURCE[0]}" | sed 's/^# \?//'; exit 0 ;;
    *) echo "unknown argument: $arg" >&2; exit 2 ;;
  esac
done

RESULTS="$ROOT/results"
mkdir -p "$RESULTS"
STAMP="$(date -u +%Y%m%d)"
PY="${PY:-$ROOT/.venv/bin/python}"
[[ -x "$PY" ]] || PY=python3

step() { printf '\n\033[1m==> %s\033[0m\n' "$1"; }
fail() { printf '\033[31mFAILED: %s\033[0m\n' "$1" >&2; }

# --- preflight ---------------------------------------------------------------

step "preflight — what this account will allow"
if ! "$PY" -m lab doctor; then
  echo
  echo "doctor reported failures. Deployment needs iam:CreateRole and the three"
  echo "bedrock tag permissions; the answer stage additionally needs InvokeModel."
  echo "Continuing anyway — terraform will fail loudly if a grant is missing."
fi

# --- deploy ------------------------------------------------------------------

step "terraform apply"
if ! terraform -chdir=infrastructure apply -auto-approve; then
  fail "terraform apply. Nothing below can run without an endpoint."
  echo
  echo "If this failed on iam:CreateRole, that is the documented blocker (V-29):"
  echo "  no execution role means no Lambda, hence no endpoint to probe or time."
  exit 1
fi

API_BASE="$(terraform -chdir=infrastructure output -raw api_base_url)"
GUARDRAIL_ID="$(terraform -chdir=infrastructure output -raw guardrail_id)"
export GUARDRAIL_ID
echo "endpoint  $API_BASE"
echo "guardrail $GUARDRAIL_ID"

step "waiting for the endpoint to answer"
for _ in $(seq 1 30); do
  curl -sf "$API_BASE/health" >/dev/null && break
  sleep 2
done
curl -sf "$API_BASE/health" || { fail "endpoint never became healthy"; exit 1; }
echo "healthy"

# --- task 26: SDK parity -----------------------------------------------------

step "task 26 — SDK parity, deployed versus local"

DEPLOYED_SDK="$RESULTS/sdk-deployed-$STAMP.json"
LOCAL_SDK="$RESULTS/sdk-local-$STAMP.json"

curl -sf "$API_BASE/api/diagnostics/sdk" -o "$DEPLOYED_SDK" \
  || { fail "could not read deployed diagnostics"; exit 1; }

# The same endpoint served locally, so the two are produced by identical code.
( cd backend && GUARDRAIL_ID="$GUARDRAIL_ID" "$PY" -c "
from fastapi.testclient import TestClient
from app.main import app
import json, sys
json.dump(TestClient(app).get('/api/diagnostics/sdk').json(), open(sys.argv[1], 'w'), indent=1)
" "$LOCAL_SDK" ) || fail "local diagnostics failed (non-fatal)"

"$PY" - "$DEPLOYED_SDK" "$LOCAL_SDK" <<'PYEOF'
import json, sys

dep = json.load(open(sys.argv[1]))
try:
    loc = json.load(open(sys.argv[2]))
except Exception:
    loc = {}

rows = [
    ("boto3", loc.get("boto3"), dep.get("boto3")),
    ("botocore", loc.get("botocore"), dep.get("botocore")),
    ("python", loc.get("python"), dep.get("python")),
    ("architecture", loc.get("architecture"), dep.get("architecture")),
    ("region", loc.get("region"), dep.get("region")),
    ("runtime", loc.get("environment"), dep.get("lambda_runtime") or dep.get("environment")),
]
width = max(len(r[0]) for r in rows)
print(f"\n  {'':<{width}}  {'local':<24} deployed")
for name, a, b in rows:
    flag = "" if a == b else "   <- differs"
    print(f"  {name:<{width}}  {str(a):<24} {b}{flag}")

print("\n  probes (deployed):")
rejected = []
for site, probe in dep.get("probes", {}).items():
    state = "accepted" if probe.get("accepted") else "REJECTED"
    print(f"    {site:<8} outputScope=FULL {state}"
          f"   NONE-action assessments: {probe.get('assessments_with_action_none')}")
    if not probe.get("accepted"):
        rejected.append(site)
        print(f"      verbatim: {probe.get('rejection')}")

print(f"\n  utc {dep.get('utc')}  ·  {dep.get('boto3')}/{dep.get('botocore')}"
      f"  ·  {dep.get('lambda_runtime')}  ·  {dep.get('architecture')}"
      f"  ·  {dep.get('region')}")

# Exit 3 signals task 27 is warranted; the caller branches on it.
sys.exit(3 if rejected else 0)
PYEOF
PARITY=$?

# --- task 27: pin the SDK, only if warranted ---------------------------------

step "task 27 — ship the pinned SDK?"
if [[ $PARITY -eq 3 ]]; then
  echo "The deployed runtime REJECTED a field this code sends."
  echo "Rebuilding with --pin-sdk so the pinned SDK travels with the bundle."
  ./scripts/package-backend.sh --pin-sdk
  terraform -chdir=infrastructure apply -auto-approve \
    || { fail "redeploy with pinned SDK"; exit 1; }

  for _ in $(seq 1 30); do curl -sf "$API_BASE/health" >/dev/null && break; sleep 2; done
  curl -sf "$API_BASE/api/diagnostics/sdk" -o "$RESULTS/sdk-deployed-pinned-$STAMP.json"

  "$PY" - "$RESULTS/sdk-deployed-pinned-$STAMP.json" "$ROOT/backend/dist/bundle-info.json" <<'PYEOF'
import json, sys
d = json.load(open(sys.argv[1]))
b = json.load(open(sys.argv[2]))
print(f"\n  after pinning: boto3 {d.get('boto3')} / botocore {d.get('botocore')}")
for site, probe in d.get("probes", {}).items():
    print(f"    {site:<8} {'accepted' if probe.get('accepted') else 'STILL REJECTED'}")
print(f"  bundle: {b.get('size_human')} ({b.get('size_bytes')} bytes), "
      f"boto3 in bundle: {b.get('boto3_in_bundle')}")
PYEOF
else
  echo "No change needed: the deployed runtime accepted every field this code sends."
  echo "Recording that as the finding. Stripping boto3 stays correct — shipping it"
  echo "would take the bundle from 9.0M to 37M for no benefit."
fi

# --- task 28: latency --------------------------------------------------------

step "task 28 — deployed latency, cold and warm"
LAT_ARGS=(--api-base "$API_BASE" --warm 3 --out "$RESULTS/latency-$STAMP.jsonl")
[[ "$WAIT_COLD" == true ]] && LAT_ARGS+=(--wait-cold)
"$PY" -m lab latency "${LAT_ARGS[@]}" || fail "some latency samples failed (recorded)"

# --- conformance against the deployed guardrail ------------------------------

step "conformance against the deployed guardrail"
"$PY" -m lab conformance --repeat 5 --out "$RESULTS/conformance-deployed-$STAMP.jsonl" \
  || fail "conformance reported failures (recorded)"

# --- summary -----------------------------------------------------------------

step "what was written"
ls -1 "$RESULTS"/*"$STAMP"* 2>/dev/null | sed 's|^|  |'
cat <<EOF

Next: fold these into docs/validation-log.md and docs/results.md, replacing the
"not measured" rows for deployed SDK parity and deployed latency.
EOF

if [[ "$DESTROY_AFTER" == true ]]; then
  step "terraform destroy"
  terraform -chdir=infrastructure destroy -auto-approve \
    || terraform -chdir=infrastructure destroy -auto-approve -refresh=false \
    || fail "destroy — run 'python -m lab teardown' to remove the guardrail by name"
else
  echo
  echo "The stack is still running. Tear it down with:"
  echo "  terraform -chdir=infrastructure destroy    # add -refresh=false if tags are denied"
fi
