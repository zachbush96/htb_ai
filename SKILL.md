#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [ ! -f .env ]; then
  cp .env.example .env
  echo "[bootstrap] Created .env from .env.example"
fi

set -a
source .env || true
set +a

STATE_DIR="${HTBMC_STATE_DIR:-$HOME/my_data/htb-mission-control-state}"
STATE_DIR="$(eval echo "$STATE_DIR")"
mkdir -p "$STATE_DIR/targets" "$STATE_DIR/memory/mistakes" "$STATE_DIR/app_logs"

echo "[bootstrap] State dir: $STATE_DIR"

python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r backend/requirements.txt

if command -v npm >/dev/null 2>&1; then
  echo "[bootstrap] Installing frontend dependencies"
  (cd frontend && npm install)
  echo "[bootstrap] Building frontend"
  (cd frontend && npm run build)
else
  echo "[bootstrap] npm not found. Backend will run, but frontend build is unavailable."
fi

if command -v codex >/dev/null 2>&1; then
  echo "[bootstrap] Codex detected: $(codex --version 2>/dev/null || echo installed)"
else
  echo "[bootstrap] Codex not found. Agent planner will use fallback until Codex is installed/configured."
fi

echo "[bootstrap] Done. Run ./scripts/run_dev.sh"
