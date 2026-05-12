#!/usr/bin/env bash
set -euo pipefail

# Backward-compatible root wrapper. The documented backend launcher is
# scripts/run_dev.sh; this file exists so older notes and shell history still
# work.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
exec ./scripts/run_dev.sh "$@"
