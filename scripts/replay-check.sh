#!/usr/bin/env bash
# Prove Replay_Mode serves the whole pipeline with AWS entirely absent.
set -uo pipefail
cd "$(dirname "$0")/../backend"
source ../.venv/bin/activate

env -u AWS_PROFILE -u AWS_REGION -u AWS_DEFAULT_REGION -u AWS_ACCESS_KEY_ID \
    -u AWS_SECRET_ACCESS_KEY -u AWS_SESSION_TOKEN -u GUARDRAIL_ID \
    AWS_CONFIG_FILE=/dev/null AWS_SHARED_CREDENTIALS_FILE=/dev/null \
    REPLAY_MODE=true CORS_ALLOW_ORIGINS='*' \
    python -m uvicorn app.main:app --port 8099 --log-level warning &
server=$!
trap 'kill $server 2>/dev/null' EXIT

for _ in $(seq 1 30); do
  curl -sf localhost:8099/health >/dev/null && break
  sleep 0.5
done

probe() {
  curl -sS localhost:8099/api/ask -H 'content-type: application/json' \
    -d "$(python -c 'import json,sys;print(json.dumps({"input":sys.argv[1]}))' "$1")" \
  | python -c '
import json, sys
d = json.load(sys.stdin)
if "stages" not in d:
    print("  409/err:", json.dumps(d)[:100]); raise SystemExit
print("  stages", [s["stage"] for s in d["stages"]],
      "| stopped", d["stopped_at"],
      "| any model:", any(s["model_invoked"] for s in d["stages"]),
      "| replayed:", bool(d["stages"][0]["replayed"]))
print("  final:", d["final"][:72])'
}

echo "in scope (three stages):";  probe "When are the collection points open?"
echo "masked (must continue):";   probe "I am Grace Wanjiku, member HG-004182, my number is 0722135790. Has my payment gone out?"
echo "blocked (stops at screen):"; probe "How many millilitres of fungicide do I put in a 20 litre knapsack?"
echo "unrecorded (409):";         probe "a prompt nobody ever recorded"
