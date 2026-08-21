#!/usr/bin/env bash
# Build the Lambda bundle at backend/build/.
#
# Terraform calls this automatically (see infrastructure/lambda.tf), and it is
# safe to run by hand. Dependencies are installed for the Lambda's platform, not
# the host's — boto3 and pydantic-core ship compiled wheels, so a Linux/arm64
# target is required or the function fails at import time on a mac or Windows box.
set -euo pipefail

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
# boto3 and botocore are provided by the Lambda runtime; shipping them roughly
# triples the bundle and slows cold starts for no benefit.
rm -rf "$BUILD/boto3" "$BUILD/botocore" "$BUILD/dateutil" "$BUILD/s3transfer" \
       "$BUILD/jmespath" "$BUILD/urllib3" "$BUILD"/python_dateutil* 2>/dev/null || true

echo "==> built $(du -sh "$BUILD" | cut -f1) in $BUILD"
