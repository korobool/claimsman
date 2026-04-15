#!/usr/bin/env bash
# Bootstrap a Claimsman checkout for first-time run or CI.
# Idempotent: re-running is safe.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "[bootstrap] root=$ROOT"

# 1. Python virtualenv + deps
if [ ! -d .venv ]; then
  echo "[bootstrap] creating Python venv at .venv"
  if ! python3 -m venv .venv 2>/dev/null; then
    echo "[bootstrap] ensurepip missing; falling back to --without-pip + get-pip.py"
    rm -rf .venv
    python3 -m venv --without-pip .venv
    curl -sSL https://bootstrap.pypa.io/get-pip.py | .venv/bin/python
  fi
fi
# shellcheck disable=SC1091
source .venv/bin/activate
pip install --upgrade pip >/dev/null
pip install -r requirements.txt

# 2. Frontend deps + build
pushd apps/frontend >/dev/null
echo "[bootstrap] installing frontend deps (npm ci)"
if [ -f package-lock.json ]; then
  npm ci
else
  npm install
fi
echo "[bootstrap] building frontend → apps/web/static/app"
npm run build
popd >/dev/null

# 3. .env
if [ ! -f .env ]; then
  cp deploy/.env.example .env
  echo "[bootstrap] wrote .env from deploy/.env.example"
fi

echo "[bootstrap] done"
