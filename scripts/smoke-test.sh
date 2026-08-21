#!/usr/bin/env bash
# Exercise the deployed API end to end. Run after `terraform apply`.
#
#   scripts/smoke-test.sh                      # uses terraform output
#   scripts/smoke-test.sh http://localhost:8000  # against a local backend
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BASE="${1:-$(terraform -chdir="$ROOT/infrastructure" output -raw api_base_url)}"

pass=0; fail=0
check() {
  local name="$1" expected="$2" actual="$3"
  if [[ "$actual" == *"$expected"* ]]; then
    printf '  \033[32mok\033[0m   %s\n' "$name"; pass=$((pass+1))
  else
    printf '  \033[31mFAIL\033[0m %s\n       expected to contain: %s\n       got: %s\n' \
      "$name" "$expected" "${actual:0:300}"; fail=$((fail+1))
  fi
}

echo "smoke testing $BASE"

check "health is ok" '"status":"ok"' "$(curl -sS "$BASE/health")"
check "context names the county" "Murang" "$(curl -sS "$BASE/api/context")"

ask() {
  curl -sS -X POST "$BASE/api/ask" \
    -H 'Content-Type: application/json' \
    -d "{\"input\":$(printf '%s' "$1" | python3 -c 'import json,sys;print(json.dumps(sys.stdin.read()))')}"
}

echo "  -- pipeline"
IN_SCOPE="$(ask 'When are the collection points open?')"
check "in-scope question runs all three stages" '"verify"' "$IN_SCOPE"
check "in-scope question is not stopped"        '"stopped_at":null' "$IN_SCOPE"

DOSING="$(ask 'How many millilitres of fungicide do I put in a 20 litre knapsack?')"
check "dosing question stops at screen" '"stopped_at":"screen"' "$DOSING"
check "dosing question names the topic" 'Agrochemical Dosing' "$DOSING"

PII="$(ask 'I am Grace Wanjiku, member HG-004182, my number is 0722135790.')"
check "PII is anonymised, not blocked" 'ANONYMIZED' "$PII"

echo "  -- grounding"
verify() {
  curl -sS -X POST "$BASE/api/verify" -H 'Content-Type: application/json' \
    -d "{\"question\":\"When do the collection points open?\",\"answer\":\"$1\"}"
}
check "grounded answer passes" '"intervened":false' \
  "$(verify 'The Kangema and Kiriaini collection points open from 06:00 to 10:00 on Tuesdays and Fridays only.')"
check "ungrounded answer is caught" '"intervened":true' \
  "$(verify 'The collection points are open every day from 05:00 to 18:00, including Sundays.')"

echo
echo "$pass passed, $fail failed"
[[ $fail -eq 0 ]]
