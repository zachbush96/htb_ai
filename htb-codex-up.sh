#!/usr/bin/env bash
# Durable launcher intended to live at:
#   /my_data/htb-codex-up.sh
#
# First-time use:
#   cp htb-codex-up.sh /my_data/htb-codex-up.sh
#   chmod +x /my_data/htb-codex-up.sh
#   nano /my_data/.htb-codex.env
#
# Daily use:
#   bash /my_data/htb-codex-up.sh

set -Eeuo pipefail

DATA_DIR="${DATA_DIR:-$HOME/my_data}"
ENV_FILE="${ENV_FILE:-$DATA_DIR/.htb-codex.env}"
WORKDIR="${WORKDIR:-$DATA_DIR/.cache/htb-codex-bootstrap}"

log() { printf '\n[htb-codex-up] %s\n' "$*"; }
die() { printf '\n[htb-codex-up] ERROR: %s\n' "$*" >&2; exit 1; }

if [[ ! -d "$DATA_DIR" ]]; then
  die "$DATA_DIR does not exist. Are you running this from HTB PwnBox?"
fi

if [[ -f "$ENV_FILE" ]]; then
  chmod 600 "$ENV_FILE" 2>/dev/null || true
  # shellcheck disable=SC1090
  source "$ENV_FILE"
else
  cat > "$ENV_FILE" <<'EOF'
# Required for private GitHub repo clone.
# Create a fine-grained GitHub token with read-only Contents access to zachbush96/htb.
GITHUB_TOKEN=""

# Required if install.sh should run Tailscale non-interactively.
# Create a Tailscale auth key tagged tag:htb, ephemeral, reusable if you want repeated use.
TS_AUTHKEY=""

# Optional. Only needed if you want API-key fallback instead of interactive ChatGPT login.
OPENAI_API_KEY=""

# Repo defaults. This project is htb_ai; change only if you intentionally keep
# your bootstrap installer in a different private repo.
BOOTSTRAP_REPO="zachbush96/htb_ai"
BOOTSTRAP_BRANCH="main"
EOF
  chmod 600 "$ENV_FILE" 2>/dev/null || true
  die "Created $ENV_FILE. Fill in GITHUB_TOKEN and TS_AUTHKEY, then rerun."
fi

: "${BOOTSTRAP_REPO:=zachbush96/htb_ai}"
: "${BOOTSTRAP_BRANCH:=main}"
: "${GITHUB_TOKEN:?Missing GITHUB_TOKEN in $ENV_FILE}"

log "Installing minimal clone dependencies"
sudo apt-get update -y
sudo apt-get install -y git curl ca-certificates

log "Refreshing private bootstrap repo: $BOOTSTRAP_REPO@$BOOTSTRAP_BRANCH"
rm -rf "$WORKDIR"
mkdir -p "$(dirname "$WORKDIR")"

# Avoid printing token in command traces.
git clone --depth 1 --branch "$BOOTSTRAP_BRANCH" \
  "https://x-access-token:${GITHUB_TOKEN}@github.com/${BOOTSTRAP_REPO}.git" \
  "$WORKDIR"

cd "$WORKDIR"

if [[ ! -f "./install.sh" ]]; then
  die "Repo cloned, but install.sh was not found at repo root."
fi

chmod +x ./install.sh
log "Running repo installer"
export DATA_DIR
export ENV_FILE
bash ./install.sh

log "Done. Try: htb-codex"
