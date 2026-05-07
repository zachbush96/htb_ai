#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
source .venv/bin/activate
export PYTHONPATH="$ROOT/backend:${PYTHONPATH:-}"
HOST="${HTBMC_BIND_HOST:-127.0.0.1}"
PORT="${HTBMC_PORT:-8000}"
uvicorn htbmc.app:app --host "$HOST" --port "$PORT" --app-dir backend
