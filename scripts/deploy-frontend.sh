#!/usr/bin/env bash
# Build the Next.js static export and push it to Amplify Hosting.
#
# Used when Amplify has no Git repository connected (the default), so no personal
# access token is needed. Reads the API URL and Amplify ids from Terraform outputs.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TF="$ROOT/infrastructure"
FE="$ROOT/frontend"

command -v aws >/dev/null || { echo "aws CLI not found"; exit 1; }
command -v jq  >/dev/null || { echo "jq not found"; exit 1; }

echo "==> reading terraform outputs"
APP_ID="$(terraform -chdir="$TF" output -raw amplify_app_id)"
BRANCH="$(terraform -chdir="$TF" output -raw amplify_branch)"
API_URL="$(terraform -chdir="$TF" output -raw api_base_url)"
# The API URL embeds the Region: https://<id>.execute-api.<region>.amazonaws.com
REGION="$(printf '%s' "$API_URL" | sed -n 's|.*execute-api\.\([a-z0-9-]*\)\.amazonaws.*|\1|p')"
REGION="${REGION:-${AWS_REGION:-eu-west-1}}"

echo "    app      $APP_ID"
echo "    branch   $BRANCH"
echo "    api      $API_URL"

echo "==> building frontend"
cd "$FE"
npm ci --silent
NEXT_PUBLIC_API_BASE_URL="$API_URL" npm run build

echo "==> zipping out/"
cd "$FE/out"
rm -f ../deploy.zip
zip -qr ../deploy.zip .
cd "$FE"

echo "==> requesting an upload slot"
DEPLOY="$(aws amplify create-deployment \
  --app-id "$APP_ID" --branch-name "$BRANCH" --region "$REGION" --output json)"
JOB_ID="$(echo "$DEPLOY" | jq -r '.jobId')"
UPLOAD_URL="$(echo "$DEPLOY" | jq -r '.zipUploadUrl')"

echo "==> uploading bundle (job $JOB_ID)"
curl -sS -X PUT -T deploy.zip -H "Content-Type: application/zip" "$UPLOAD_URL"

echo "==> starting deployment"
aws amplify start-deployment \
  --app-id "$APP_ID" --branch-name "$BRANCH" --job-id "$JOB_ID" \
  --region "$REGION" --output json | jq -r '.jobSummary | "    status: \(.status)"'

echo
echo "==> deployed: https://${BRANCH}.${APP_ID}.amplifyapp.com"
echo "    (first deploy takes a minute to go live)"
rm -f deploy.zip
