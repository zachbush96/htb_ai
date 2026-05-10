#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
if [ -f .env ]; then
  set -a
  source .env
  set +a
fi
source .venv/bin/activate
HOST="${HTBMC_BIND_HOST:-127.0.0.1}"
PORT="${HTBMC_PORT:-8000}"
export PYTHONPATH="$ROOT/backend:${PYTHONPATH:-}"
echo "[run] http://$HOST:$PORT"
uvicorn htbmc.app:app --host "$HOST" --port "$PORT" --reload --app-dir backend
