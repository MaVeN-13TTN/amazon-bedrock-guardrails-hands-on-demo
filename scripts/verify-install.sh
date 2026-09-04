#!/usr/bin/env bash
# verify-install.sh — is this checkout correctly installed and internally consistent?
#
# Runs everything that needs no AWS account, then reports what AWS access would
# add. Creates nothing, deletes nothing, spends nothing.
#
# Three kinds of result, and the distinction matters:
#   PASS   checked and correct
#   FAIL   checked and wrong — the exit status is non-zero
#   SKIP   could not be checked, with the reason. Never counted as a pass.
#
# Usage:
#   verify-install.sh              local checks only (no credentials needed)
#   verify-install.sh --with-aws   also probe the account via `lab doctor`
#   verify-install.sh --quick      skip the slow suites (frontend, e2e)
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

WITH_AWS=false
QUICK=false
for arg in "$@"; do
  case "$arg" in
    --with-aws) WITH_AWS=true ;;
    --quick)    QUICK=true ;;
    -h|--help)  sed -n '2,16p' "${BASH_SOURCE[0]}" | sed 's/^# \?//'; exit 0 ;;
    *) echo "unknown argument: $arg" >&2; exit 2 ;;
  esac
done

pass=0; fail=0; skip=0
declare -a FAILURES=() SKIPS=()

if [[ -t 1 ]]; then
  G=$'\033[32m'; R=$'\033[31m'; Y=$'\033[33m'; B=$'\033[1m'; N=$'\033[0m'
else
  G=""; R=""; Y=""; B=""; N=""
fi

section() { printf '\n%s%s%s\n' "$B" "$1" "$N"; }
ok()   { printf '  %s[ pass ]%s %s\n' "$G" "$N" "$1"; pass=$((pass+1)); }
bad()  { printf '  %s[ FAIL ]%s %s\n' "$R" "$N" "$1"; fail=$((fail+1)); FAILURES+=("$1${2:+ — $2}"); }
miss() { printf '  %s[ skip ]%s %s %s(%s)%s\n' "$Y" "$N" "$1" "$Y" "$2" "$N"; skip=$((skip+1)); SKIPS+=("$1 — $2"); }

# Run a command quietly; pass on exit 0, fail otherwise, showing the tail on failure.
check() {
  local label="$1"; shift
  local log; log="$(mktemp)"
  if "$@" >"$log" 2>&1; then
    ok "$label"
    rm -f "$log"
  else
    bad "$label" "$(tail -3 "$log" | tr '\n' ' ')"
    printf '           %s\n' "$(tail -5 "$log" | sed 's/^/           /')" >&2
    rm -f "$log"
  fi
}

have() { command -v "$1" >/dev/null 2>&1; }

# --- 1. tools ----------------------------------------------------------------

section "1 · required tools"

PY=""
for candidate in "$ROOT/.venv/bin/python" python3 python; do
  if have "$candidate" || [[ -x "$candidate" ]]; then PY="$candidate"; break; fi
done

if [[ -z "$PY" ]]; then
  bad "python" "not found on PATH and no .venv"
else
  pyv="$("$PY" -c 'import sys;print("%d.%d"%sys.version_info[:2])' 2>/dev/null)"
  if "$PY" -c 'import sys;sys.exit(0 if sys.version_info>=(3,12) else 1)' 2>/dev/null; then
    ok "python $pyv (>= 3.12)"
  else
    bad "python $pyv" "3.12 or newer is required"
  fi
  [[ "$PY" == *".venv"* ]] && ok "virtualenv at .venv" \
    || miss "virtualenv at .venv" "using system python; a venv is recommended"
fi

if have terraform; then
  # versions.tf requires >= 1.7.0. Reporting the version without checking it let an
  # attendee on 1.6 pass every check here and then fail at `terraform init`.
  tfv="$(terraform version -json 2>/dev/null | "$PY" -c 'import json,sys;print(json.load(sys.stdin)["terraform_version"])' 2>/dev/null || echo "")"
  if [[ -z "$tfv" ]]; then
    ok "terraform present (version not reported)"
  elif "$PY" -c 'import sys;v=tuple(int(x) for x in sys.argv[1].split(".")[:3]);sys.exit(0 if v>=(1,7,0) else 1)' "$tfv"; then
    ok "terraform $tfv (>= 1.7.0)"
  else
    bad "terraform $tfv" "infrastructure/versions.tf requires >= 1.7.0"
  fi
else
  miss "terraform" "needed only to create the guardrail"
fi

have aws  && ok "aws cli $(aws --version 2>&1 | cut -d' ' -f1)" || miss "aws cli" "needed only for teardown-by-name and doctor"
have node && ok "node $(node --version)" || miss "node" "needed only for the web UI"
have npm  && ok "npm $(npm --version)"   || miss "npm" "needed only for the web UI"
have curl && ok "curl" || miss "curl" "needed by smoke-test.sh and deploy-and-validate.sh"

# --- 2. python dependencies --------------------------------------------------

section "2 · python dependencies"

if [[ -n "$PY" ]]; then
  for mod in fastapi pydantic pydantic_settings mangum boto3 botocore; do
    if "$PY" -c "import $mod" 2>/dev/null; then
      ok "import $mod"
    else
      bad "import $mod" "pip install -r backend/requirements.txt"
    fi
  done

  # The SDK floor is load-bearing twice over: outputScope on the request (V-14)
  # and tier on the response (V-24). A version check alone is not enough —
  # what matters is whether the bundled service model declares the fields.
  "$PY" - <<'PYEOF'
import sys
try:
    import boto3, botocore, botocore.session
except ImportError:
    sys.exit(9)
s = botocore.session.get_session()
rt = s.get_service_model("bedrock-runtime")
has_scope = "outputScope" in rt.operation_model("ApplyGuardrail").input_shape.members
topic = s.get_service_model("bedrock").operation_model("GetGuardrail").output_shape.members.get("topicPolicy")
has_tier = topic is not None and "tier" in topic.members
# Exit status is the whole result. Printing here would land in the middle of the
# report, which is why this probe used to emit a stray "1.38.0 1.38.46 1 1" line.
sys.exit(0 if (has_scope and has_tier) else 1)
PYEOF
  rc=$?
  sdk="$("$PY" -c 'import boto3,botocore;print(boto3.__version__,botocore.__version__)' 2>/dev/null)"
  case $rc in
    0) ok "boto3 $sdk carries outputScope (request) and tier (response)" ;;
    9) bad "boto3 service model" "boto3 is not importable" ;;
    *) bad "boto3 $sdk is missing a field this code uses" \
           "pin is 1.38.0 — see validation log V-14 and V-24" ;;
  esac

  for tool in pytest ruff; do
    "$PY" -m "$tool" --version >/dev/null 2>&1 && ok "$tool available" \
      || miss "$tool" "pip install -r backend/requirements-dev.txt"
  done
fi

# --- 3. repository layout ----------------------------------------------------

section "3 · repository layout"

for f in shared/scenario.json backend/app/main.py backend/app/guardrails.py \
         backend/app/replay.py lab/__main__.py lab/cases.json lab/checkpoints.json \
         infrastructure/guardrail.tf infrastructure/regions.tf \
         frontend/package.json README.md ADR.md; do
  [[ -f "$f" ]] && ok "$f" || bad "$f" "missing from the checkout"
done

for s in package-backend.sh deploy-frontend.sh smoke-test.sh replay-check.sh \
         deploy-and-validate.sh verify-install.sh measure-tier-gap.py; do
  if [[ -f "scripts/$s" ]]; then
    [[ -x "scripts/$s" ]] && ok "scripts/$s executable" \
      || bad "scripts/$s not executable" "chmod +x scripts/$s"
  else
    bad "scripts/$s" "missing"
  fi
done

# --- 4. the shared contract --------------------------------------------------

section "4 · shared/scenario.json — the single source of truth"

if [[ -n "$PY" ]]; then
  "$PY" - <<'PYEOF'
import json, sys, pathlib
raw = json.loads(pathlib.Path("shared/scenario.json").read_text())
required = ["guardrail_name", "system_prompt", "extension_bulletin", "denied_topics",
            "content_filters", "blocked_words", "pii_entities", "pii_regexes",
            "grounding_threshold", "relevance_threshold", "bulletin_facts",
            "about_sections", "blocked_input_message", "blocked_output_message"]
missing = [k for k in required if k not in raw]
if missing:
    print("missing keys: " + ", ".join(missing)); sys.exit(1)

# A denied-topic definition over 200 characters is silently rejected by AWS (V-16).
long = [t["name"] for t in raw["denied_topics"] if len(t["definition"]) > 200]
if long:
    print("topic definitions over the undocumented 200-char cap: " + ", ".join(long))
    sys.exit(2)

# Regexes must survive JSON escaping and compile.
import re
for r in raw["pii_regexes"]:
    re.compile(r["pattern"])
PYEOF
  contract_rc=$?
  contract_summary="$("$PY" - <<'PYEOF'
import json, pathlib
d = json.loads(pathlib.Path("shared/scenario.json").read_text())
print(f'{len(d["denied_topics"])} topics, {len(d["content_filters"])} filters, '
      f'{len(d["blocked_words"])} words, {len(d["pii_entities"])} entities, '
      f'{len(d["pii_regexes"])} regexes')
PYEOF
)"
  case $contract_rc in
    0) ok "scenario.json is complete and valid — $contract_summary" ;;
    1) bad "scenario.json is missing required keys" ;;
    2) bad "a denied-topic definition exceeds 200 characters" "AWS rejects it — V-16" ;;
    *) bad "scenario.json is invalid" "a regex may not compile" ;;
  esac

  # The app and Terraform must read the same file, and the app asserts this at
  # import time via a drift guard.
  check "app imports scenario without drift" "$PY" -c "import sys;sys.path.insert(0,'backend');import app.scenario"
fi

# --- 5. test suites ----------------------------------------------------------

section "5 · test suites"

if [[ -n "$PY" ]] && "$PY" -m pytest --version >/dev/null 2>&1; then
  check "backend tests" "$PY" -m pytest backend/tests -q
  check "lab tests"     "$PY" -m pytest lab -q
else
  miss "backend and lab tests" "pytest is not installed"
fi

if [[ -n "$PY" ]] && "$PY" -m ruff --version >/dev/null 2>&1; then
  check "ruff lint" "$PY" -m ruff check lab backend
else
  miss "ruff lint" "ruff is not installed"
fi

if [[ "$QUICK" == true ]]; then
  miss "frontend tests" "--quick was given"
  miss "typescript" "--quick was given"
elif have npm && [[ -d frontend/node_modules ]]; then
  check "frontend tests" npm --prefix frontend run test -- --run
  check "typescript compiles" npx --prefix frontend tsc --noEmit -p frontend/tsconfig.json
else
  miss "frontend tests" "run 'npm --prefix frontend install' first"
  miss "typescript" "run 'npm --prefix frontend install' first"
fi

# --- 6. infrastructure -------------------------------------------------------

section "6 · infrastructure"

if have terraform; then
  if [[ -d infrastructure/.terraform ]]; then
    check "terraform validate" terraform -chdir=infrastructure validate
  else
    miss "terraform validate" "run 'terraform -chdir=infrastructure init' first"
  fi
  check "terraform fmt" terraform -chdir=infrastructure fmt -check -recursive
else
  miss "terraform validate" "terraform is not installed"
fi

for s in scripts/*.sh; do
  bash -n "$s" 2>/dev/null && ok "$(basename "$s") parses" || bad "$(basename "$s")" "syntax error"
done

# --- 7. documentation --------------------------------------------------------

section "7 · documentation"

if [[ -n "$PY" ]]; then
  "$PY" - <<'PYEOF'
import pathlib, re, sys
bad = []
for md in pathlib.Path(".").rglob("*.md"):
    if any(p in str(md) for p in ("node_modules", ".venv", ".git/", "build/")):
        continue
    for link in re.findall(r"\[[^\]]*\]\(([^)#\s]+)(?:#[^)]*)?\)", md.read_text(errors="ignore")):
        if link.startswith(("http", "mailto:")):
            continue
        if not (md.parent / link).resolve().exists():
            bad.append(f"{md}: {link}")
for b in bad:
    print(b)
sys.exit(1 if bad else 0)
PYEOF
  [[ $? -eq 0 ]] && ok "no broken relative links in any markdown file" \
                 || bad "broken relative links" "listed above"

  check "architecture.svg is well-formed XML" \
    "$PY" -c "import xml.dom.minidom;xml.dom.minidom.parse('docs/architecture.svg')"
fi

# --- 8. Replay_Mode ----------------------------------------------------------

section "8 · Replay_Mode (works with no AWS at all)"

fixtures=$(ls backend/app/fixtures/replay/*.json 2>/dev/null | wc -l)
if [[ "$fixtures" -gt 0 ]]; then
  ok "$fixtures recorded fixture file(s)"
  if [[ -x scripts/replay-check.sh ]]; then
    log="$(mktemp)"
    if ./scripts/replay-check.sh >"$log" 2>&1 && grep -q "stages \['screen', 'answer', 'verify'\]" "$log"; then
      ok "all three stages replay with every AWS variable unset"
    else
      bad "replay-check.sh" "$(grep -iE 'err|fail' "$log" | head -1)"
    fi
    rm -f "$log"
  fi
else
  miss "Replay_Mode fixtures" "record them with 'python -m lab conformance --record'"
fi

# --- 9. AWS (optional) -------------------------------------------------------

section "9 · AWS account"

if [[ "$WITH_AWS" != true ]]; then
  miss "account capability probe" "pass --with-aws to run 'lab doctor'"
elif [[ -z "$PY" ]]; then
  miss "account capability probe" "python is unavailable"
else
  region="${AWS_REGION:-${AWS_DEFAULT_REGION:-}}"
  if [[ -z "$region" ]]; then
    miss "account capability probe" "set AWS_REGION first"
  else
    echo "  running 'lab doctor' — creates nothing:"
    if "$PY" -m lab doctor 2>&1 | sed 's/^/    /'; then
      ok "lab doctor reports the account is ready"
    else
      miss "some AWS capabilities are absent" "doctor printed the exact fix above"
    fi
    echo
    echo "  to also check deployment permissions (creates and deletes one IAM role):"
    echo "    python -m lab doctor --check-deploy --probe-write"
  fi
fi

# --- summary -----------------------------------------------------------------

section "summary"
printf '  %s%d passed%s · %s%d failed%s · %s%d skipped%s\n' \
  "$G" "$pass" "$N" "$R" "$fail" "$N" "$Y" "$skip" "$N"

if (( fail )); then
  printf '\n%sFailures:%s\n' "$R" "$N"
  for f in "${FAILURES[@]}"; do printf '  · %s\n' "$f"; done
fi

if (( skip )); then
  printf '\n%sNot checked — these are not passes:%s\n' "$Y" "$N"
  for s in "${SKIPS[@]}"; do printf '  · %s\n' "$s"; done
fi

if (( fail == 0 )); then
  cat <<EOF

${G}${B}Installation verified.${N} Next:
  python -m lab doctor                  what your AWS account will allow
  docs/lab-guide.md                     the 90-minute self-paced lab
  docs/demo-runbook.md                  the 60-minute presented session
EOF
fi

exit $(( fail > 0 ? 1 : 0 ))
