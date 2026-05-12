#!/usr/bin/env bash
set -euo pipefail

# Start only the FastAPI backend. Pair this with scripts/run_frontend.sh for the
# browser UI. Runtime state is controlled by HTBMC_STATE_DIR, defaulting to
# ./state through env.example.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [ ! -f .venv/bin/activate ]; then
  echo "Missing .venv. Run ./scripts/bootstrap.sh first." >&2
  exit 1
fi

source .venv/bin/activate
export PYTHONPATH="$ROOT/backend:${PYTHONPATH:-}"
HOST="${HTBMC_BIND_HOST:-127.0.0.1}"
PORT="${HTBMC_PORT:-8000}"
uvicorn htbmc.app:app --host "$HOST" --port "$PORT" --app-dir backend
