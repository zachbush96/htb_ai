from __future__ import annotations

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


def _expand(value: str) -> str:
    return os.path.expandvars(os.path.expanduser(value))


APP_ROOT = Path(__file__).resolve().parents[2]
STATE_DIR = Path(_expand(os.getenv("HTBMC_STATE_DIR", "$HOME/my_data/htb-mission-control-state"))).resolve()
TARGETS_DIR = STATE_DIR / "targets"
MISTAKES_DIR = STATE_DIR / "memory" / "mistakes"
APP_LOG_DIR = STATE_DIR / "app_logs"
SCHEMA_DIR = APP_ROOT / "schemas"
PROMPT_DIR = APP_ROOT / "prompts"

BIND_HOST = os.getenv("HTBMC_BIND_HOST", "127.0.0.1")
PORT = int(os.getenv("HTBMC_PORT", "8000"))
AUTO_PUSH = os.getenv("HTBMC_AUTO_PUSH", "false").lower() == "true"
STATE_GIT_REMOTE = os.getenv("HTBMC_STATE_GIT_REMOTE", "").strip()
MAX_RAW_OUTPUT_BYTES = int(os.getenv("HTBMC_MAX_RAW_OUTPUT_BYTES", "1048576"))
CODEX_ENABLED = os.getenv("HTBMC_CODEX_ENABLED", "true").lower() == "true"
CODEX_BIN = os.getenv("CODEX_BIN", "codex")
CODEX_PROFILE = os.getenv("CODEX_PROFILE", "").strip()
AUTO_HOSTS = os.getenv("HTBMC_AUTO_HOSTS", "true").lower() == "true"


def ensure_dirs() -> None:
    for p in [STATE_DIR, TARGETS_DIR, MISTAKES_DIR, APP_LOG_DIR]:
        p.mkdir(parents=True, exist_ok=True)
