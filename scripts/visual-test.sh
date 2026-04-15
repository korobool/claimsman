#!/usr/bin/env bash
# Placeholder for the Playwright visual test runner.
# A real suite lands in M2 under apps/frontend/tests/visual/.
set -euo pipefail
BASE_URL="${CLAIMSMAN_BASE_URL:-http://108.181.157.13:8811}"
echo "[visual-test] probing $BASE_URL/healthz"
curl -fsS "$BASE_URL/healthz" && echo
echo "[visual-test] probing $BASE_URL/api/v1/system/healthz"
curl -fsS "$BASE_URL/api/v1/system/healthz" && echo
echo "[visual-test] probing $BASE_URL/app/"
curl -fsSI "$BASE_URL/app/" | head -1
