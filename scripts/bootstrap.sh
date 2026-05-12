#!/usr/bin/env bash
set -euo pipefail

# Bootstrap installs the Python backend and Vite frontend dependencies from a
# clean checkout. It is intentionally conservative about Python versions because
# the project has been validated on Python 3.11, 3.12, and 3.13.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

cp -n env.example .env || true

choose_python() {
  # Preference order:
  # 1. HTBMC_PYTHON_BIN, when the operator pins a known-good interpreter.
  # 2. Explicit supported python3.x binaries.
  # 3. python3, only if it resolves to a supported minor version.
  local candidate version_mm
  for candidate in "${HTBMC_PYTHON_BIN:-}" python3.13 python3.12 python3.11 python3; do
    if [ -z "${candidate:-}" ] || ! command -v "$candidate" >/dev/null 2>&1; then
      continue
    fi
    version_mm="$("$candidate" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
    case "$version_mm" in
      3.11|3.12|3.13)
        printf '%s\n' "$candidate"
        return 0
        ;;
    esac
  done
  return 1
}

PYTHON_BIN="$(choose_python)" || {
  echo "No supported Python found. Install Python 3.11, 3.12, or 3.13, or set HTBMC_PYTHON_BIN." >&2
  exit 1
}

TARGET_VERSION="$("$PYTHON_BIN" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
if [ -x .venv/bin/python ]; then
  CURRENT_VERSION="$(".venv/bin/python" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || true)"
  if [ "$CURRENT_VERSION" != "$TARGET_VERSION" ]; then
    # Rebuild rather than reusing a venv created by an unsupported or different
    # interpreter. This avoids hard-to-debug import and wheel compatibility
    # failures after a local Python upgrade.
    echo "Rebuilding .venv because it currently points at Python ${CURRENT_VERSION:-unknown} and bootstrap selected Python $TARGET_VERSION."
    rm -rf .venv
  fi
fi

echo "Using Python: $PYTHON_BIN ($("$PYTHON_BIN" --version 2>&1))"
"$PYTHON_BIN" -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r backend/requirements.txt

if command -v npm >/dev/null 2>&1; then
  (cd frontend && npm install)
fi

echo "Bootstrap complete"
