#!/usr/bin/env bash
# Build the Lambda bundle at backend/build/.
#
# Terraform calls this automatically (see infrastructure/lambda.tf), and it is
# safe to run by hand. Dependencies are installed for the Lambda's platform, not
# the host's — boto3 and pydantic-core ship compiled wheels, so a Linux/arm64
# target is required or the function fails at import time on a mac or Windows box.
#
# Usage:
#   package-backend.sh              strip boto3/botocore, use the runtime's (default)
#   package-backend.sh --pin-sdk    ship the pinned boto3/botocore instead
#
# --pin-sdk exists for one specific finding: if the deployed runtime's SDK rejects
# a Bedrock field the pipeline sends, the runtime's SDK is too old and the pin has
# to travel with the code. Confirm that is actually the case before using it —
# `GET /api/diagnostics/sdk` reports whether each field was accepted — because the
# runtime's SDK is usually *newer* than the pin, and shipping ours then makes the
# bundle larger and the cold start slower for no benefit (validation log V-29).
set -euo pipefail

PIN_SDK=false
for arg in "$@"; do
  case "$arg" in
    --pin-sdk) PIN_SDK=true ;;
    -h|--help) sed -n '2,18p' "${BASH_SOURCE[0]}" | sed 's/^# \?//'; exit 0 ;;
    *) echo "unknown argument: $arg" >&2; exit 2 ;;
  esac
done

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND="$ROOT/backend"
BUILD="$BACKEND/build"
PY_VERSION="3.12"
PLATFORM="manylinux2014_aarch64" # matches architectures = ["arm64"]

echo "==> cleaning $BUILD"
rm -rf "$BUILD" "$BACKEND/dist"
mkdir -p "$BUILD" "$BACKEND/dist"

echo "==> installing dependencies for $PLATFORM / py$PY_VERSION"
python3 -m pip install \
  --quiet \
  --target "$BUILD" \
  --implementation cp \
  --python-version "$PY_VERSION" \
  --only-binary=:all: \
  --platform "$PLATFORM" \
  --upgrade \
  -r "$BACKEND/requirements.txt"

echo "==> copying application code"
cp -r "$BACKEND/app" "$BUILD/app"
cp "$BACKEND/lambda_handler.py" "$BUILD/lambda_handler.py"

# The backend reads this at runtime; SCENARIO_PATH points at the bundle root.
echo "==> copying shared/scenario.json"
cp "$ROOT/shared/scenario.json" "$BUILD/scenario.json"

echo "==> pruning"
find "$BUILD" -type d -name "__pycache__" -prune -exec rm -rf {} +
find "$BUILD" -type d -name "tests" -prune -exec rm -rf {} +
find "$BUILD" -type d -name "*.dist-info" -prune -exec rm -rf {} +

if [[ "$PIN_SDK" == true ]]; then
  # Ship the pinned SDK. Only correct when the runtime's own SDK lacks a field
  # this code sends — otherwise it is dead weight.
  pinned=$(grep -E '^boto3==' "$BACKEND/requirements.txt" || echo "boto3 (unpinned)")
  echo "==> KEEPING boto3/botocore in the bundle ($pinned)"
  echo "    the deployed function will use these, not the runtime's"
else
  # boto3 and botocore are provided by the Lambda runtime. Shipping them takes the
  # bundle from 9.0M to 37M — 4.1x, measured — and slows cold starts for no benefit.
  echo "==> stripping boto3/botocore — the runtime supplies them"
  rm -rf "$BUILD/boto3" "$BUILD/botocore" "$BUILD/dateutil" "$BUILD/s3transfer" \
         "$BUILD/jmespath" "$BUILD/urllib3" "$BUILD"/python_dateutil* 2>/dev/null || true
fi

size=$(du -sh "$BUILD" | cut -f1)
echo "==> built $size in $BUILD (pin-sdk=$PIN_SDK)"

# Recorded so the parity comparison has both numbers without a second build.
cat > "$BACKEND/dist/bundle-info.json" <<EOF
{
  "pin_sdk": $PIN_SDK,
  "size_human": "$size",
  "size_bytes": $(du -sb "$BUILD" | cut -f1),
  "boto3_in_bundle": $([[ -d "$BUILD/boto3" ]] && echo true || echo false),
  "built_utc": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
EOF
echo "==> wrote $BACKEND/dist/bundle-info.json"
