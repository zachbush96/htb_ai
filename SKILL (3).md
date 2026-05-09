#!/usr/bin/env bash
set -euo pipefail
if [ -f .env ]; then source .env; fi
STATE_DIR="${HTBMC_STATE_DIR:-$HOME/my_data/htb-mission-control-state}"
STATE_DIR="$(eval echo "$STATE_DIR")"
REMOTE="${HTBMC_STATE_GIT_REMOTE:-}"
mkdir -p "$STATE_DIR"
cd "$STATE_DIR"
git init
if [ -n "$REMOTE" ] && ! git remote | grep -q '^origin$'; then
  git remote add origin "$REMOTE"
fi
git add . || true
git commit -m "initial state" || true
echo "State repo ready at $STATE_DIR"
