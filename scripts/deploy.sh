#!/usr/bin/env bash
# Deploy Claimsman on the dev server. Intended to run from ~/workspace/claimsman.
# Responsibilities:
#   - git pull
#   - bring up Postgres via docker compose
#   - install/update python deps
#   - install/build the React SPA into apps/web/static/app
#   - (re)start the claimsman tmux session running uvicorn
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

SESSION="${CLAIMSMAN_TMUX_SESSION:-claimsman}"
PORT="${CLAIMSMAN_PORT:-8811}"

echo "[deploy] root=$ROOT session=$SESSION port=$PORT"

# 1. Update repo
if [ -d .git ]; then
  echo "[deploy] git pull"
  git pull --ff-only
fi

# 2. Ensure .env exists
if [ ! -f .env ]; then
  cp deploy/.env.example .env
  echo "[deploy] created .env from template"
fi

# 3. Start Postgres (Docker Compose v2)
echo "[deploy] docker compose up -d postgres"
docker compose --env-file .env -f deploy/docker-compose.yml up -d postgres

# 4. Python venv + deps
if [ ! -d .venv ]; then
  # Ubuntu ships venv but sometimes strips ensurepip; create without pip and
  # bootstrap pip via get-pip.py so we don't depend on the python3-venv apt
  # package being installable on the host.
  if ! python3 -m venv .venv 2>/dev/null; then
    echo "[deploy] ensurepip missing; creating venv without pip and bootstrapping"
    rm -rf .venv
    python3 -m venv --without-pip .venv
    curl -sSL https://bootstrap.pypa.io/get-pip.py | .venv/bin/python
  fi
fi
# shellcheck disable=SC1091
source .venv/bin/activate
pip install --upgrade pip >/dev/null
# Install torch separately from the CPU wheel index so we don't compete
# for VRAM with other workloads on the dev server. If torch is already
# installed, this is a fast no-op.
if ! python -c "import torch" >/dev/null 2>&1; then
  echo "[deploy] installing torch CPU wheel"
  pip install torch --index-url https://download.pytorch.org/whl/cpu
fi
pip install -r requirements.txt

# 5a. DB migrations
echo "[deploy] running alembic migrations"
set -a; source .env; set +a
alembic upgrade head

# 5b. Frontend build
pushd apps/frontend >/dev/null
if [ -f package-lock.json ]; then
  npm ci
else
  npm install
fi
npm run build
popd >/dev/null

# 6. Restart tmux session running uvicorn
if tmux has-session -t "$SESSION" 2>/dev/null; then
  echo "[deploy] killing existing tmux session $SESSION"
  tmux kill-session -t "$SESSION"
fi

echo "[deploy] starting tmux session $SESSION"
tmux new-session -d -s "$SESSION" -c "$ROOT" \
  "set -a; source .env; set +a; source .venv/bin/activate; \
   python -m apps.web.main 2>&1 | tee -a /tmp/claimsman.log"

sleep 2
echo "[deploy] health check"
for i in 1 2 3 4 5; do
  if curl -fsS "http://127.0.0.1:${PORT}/healthz" >/dev/null; then
    echo "[deploy] backend up on :${PORT}"
    exit 0
  fi
  sleep 2
done

echo "[deploy] backend did not come up on :${PORT}" >&2
tmux capture-pane -t "$SESSION" -p | tail -40 >&2 || true
exit 1
