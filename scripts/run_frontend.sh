#!/usr/bin/env bash
set -euo pipefail

# Start only the Vite frontend. API calls are proxied/configured by the Vite app
# during local development, while the backend is started separately with
# scripts/run_dev.sh.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT/frontend"

if [ ! -d node_modules ]; then
  echo "Missing frontend/node_modules. Run ./scripts/bootstrap.sh first." >&2
  exit 1
fi

HOST="${HTBMC_FRONTEND_HOST:-127.0.0.1}"
PORT="${HTBMC_FRONTEND_PORT:-5173}"
npm run dev -- --host "$HOST" --port "$PORT"
