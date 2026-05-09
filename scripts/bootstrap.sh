#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

cp -n env.example .env || true
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r backend/requirements.txt

if command -v npm >/dev/null 2>&1; then
  (cd frontend && npm install)
fi

echo "Bootstrap complete"
