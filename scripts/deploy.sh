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

# --- torch install: auto-detect GPU ------------------------------------
# Pick the right torch wheel for the host:
#   - if nvidia-smi is present and CLAIMSMAN_TORCH_CPU is not set → cu128
#     (the latest CUDA wheel that ships torch 2.11 at time of writing,
#      chosen to match Surya 0.17's torch>=2.7 requirement)
#   - otherwise → cpu
# You can force either mode with CLAIMSMAN_TORCH_CPU=1 or
# CLAIMSMAN_TORCH_INDEX=<url>.
TORCH_INDEX="${CLAIMSMAN_TORCH_INDEX:-}"
if [ -z "$TORCH_INDEX" ]; then
  if [ -n "${CLAIMSMAN_TORCH_CPU:-}" ]; then
    TORCH_INDEX="https://download.pytorch.org/whl/cpu"
  elif command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi >/dev/null 2>&1; then
    TORCH_INDEX="https://download.pytorch.org/whl/cu128"
  else
    TORCH_INDEX="https://download.pytorch.org/whl/cpu"
  fi
fi
echo "[deploy] torch index: $TORCH_INDEX"

# Check if the installed torch matches what we want (GPU vs CPU).
_torch_info() {
  python - <<'PY' 2>/dev/null || true
try:
    import torch
    print(torch.__version__, "cuda" if torch.cuda.is_available() else "cpu")
except Exception:
    pass
PY
}
_current=$(_torch_info | tr -d '\n')
if [ -z "$_current" ]; then
  echo "[deploy] installing torch ($TORCH_INDEX)"
  pip install --quiet torch --index-url "$TORCH_INDEX"
else
  # Re-install if we want cuda but installed is CPU, or vice versa.
  want_cuda=false
  case "$TORCH_INDEX" in
    *cu*) want_cuda=true ;;
  esac
  has_cuda=false
  case "$_current" in
    *cuda*) has_cuda=true ;;
  esac
  if [ "$want_cuda" = "$has_cuda" ]; then
    echo "[deploy] torch already installed: $_current"
  else
    echo "[deploy] switching torch: $_current → $TORCH_INDEX"
    pip uninstall -y torch >/dev/null
    pip install --quiet torch --index-url "$TORCH_INDEX"
  fi
fi

# Auto-enable GPU device for Surya + SigLIP if we just installed a
# CUDA wheel. Anything the user explicitly set in .env wins.
if python -c "import torch; exit(0 if torch.cuda.is_available() else 1)" 2>/dev/null; then
  if ! grep -q "^CLAIMSMAN_SURYA_DEVICE=" .env 2>/dev/null; then
    echo "CLAIMSMAN_SURYA_DEVICE=cuda" >> .env
    echo "[deploy] set CLAIMSMAN_SURYA_DEVICE=cuda in .env"
  fi
  if ! grep -q "^CLAIMSMAN_SIGLIP_DEVICE=" .env 2>/dev/null; then
    echo "CLAIMSMAN_SIGLIP_DEVICE=cuda" >> .env
    echo "[deploy] set CLAIMSMAN_SIGLIP_DEVICE=cuda in .env"
  fi
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
