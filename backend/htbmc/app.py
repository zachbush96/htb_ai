import asyncio
import fcntl
import ipaddress
import json
import os
import pty
import queue
import re
import signal
import shlex
import shutil
import subprocess
import threading
import time
import termios
import urllib.error
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, model_validator

load_dotenv()
load_dotenv(".htb-codex.env", override=False)

app = FastAPI(title="HTB Mission Control", version="0.5.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

STATE_DIR = Path(os.getenv("HTBMC_STATE_DIR", "./state")).resolve()
TARGETS_DIR = STATE_DIR / "targets"
SETTINGS_DIR = STATE_DIR / "settings"
RUNTIME_SETTINGS_PATH = SETTINGS_DIR / "runtime.json"
PLANNER_LOG_PATH = STATE_DIR / "logs" / "llm_planner.jsonl"
NMAP_BIN = os.getenv("HTBMC_NMAP_BIN", "nmap")
SCAN_TIMEOUT_SECONDS = int(os.getenv("HTBMC_SCAN_TIMEOUT_SECONDS", "1200"))
ACTION_TIMEOUT_SECONDS = int(os.getenv("HTBMC_ACTION_TIMEOUT_SECONDS", "180"))
OLLAMA_TAILSCALE_HOST = os.getenv("OLLAMA_TAILSCALE_HOST", "").strip()
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "").strip()
OLLAMA_TIMEOUT_SECONDS = float(os.getenv("HTBMC_OLLAMA_TIMEOUT_SECONDS", "5"))
PLANNER_INTERVAL_SECONDS = float(os.getenv("HTBMC_PLANNER_INTERVAL_SECONDS", "20"))
PLANNER_MAX_PENDING_ACTIONS = int(os.getenv("HTBMC_PLANNER_MAX_PENDING_ACTIONS", "6"))
PLANNER_GLOBAL_RPM = max(1, int(os.getenv("HTBMC_PLANNER_GLOBAL_RPM", "30")))
PLANNER_INFLIGHT_LIMIT = max(1, int(os.getenv("HTBMC_PLANNER_INFLIGHT_LIMIT", "2")))
PLANNER_TARGET_COOLDOWN_SECONDS = max(0.0, float(os.getenv("HTBMC_PLANNER_TARGET_COOLDOWN_SECONDS", "5")))
PLANNER_MAX_UNRESOLVED_ACTIONS = max(1, int(os.getenv("HTBMC_PLANNER_MAX_UNRESOLVED_ACTIONS", "8")))
LLM_PROMPTS_LOG_PATH = STATE_DIR / "logs" / "llm_prompts.jsonl"
STATE_SCHEMA_VERSION = 2

AUTONOMY_PROFILE_ORDER = {
    "recon_only": 0,
    "through_foothold": 1,
    "through_privesc": 2,
}
STAGE_CAPABILITY_ORDER = {
    "initial-recon": 0,
    "service-expansion": 0,
    "service-enum": 0,
    "web-fingerprint": 0,
    "targeted-web-enum": 0,
    "content-discovery": 0,
    "service-auth": 1,
    "auth-scouting": 1,
    "default-creds": 1,
    "credential-validation": 1,
    "focused-exploitation": 1,
    "initial-access": 1,
    "post-access": 2,
    "privesc": 2,
    "loot": 2,
}
NOISE_LEVEL_ORDER = {"safe": 0, "low": 1, "medium": 2, "high": 3}
TOOL_CATALOG = [
    {"name": "nmap", "family": "recon", "summary": "Service and version discovery"},
    {"name": "curl", "family": "web", "summary": "Low-noise HTTP and metadata fetches"},
    {"name": "ffuf", "family": "web", "summary": "Focused content and vhost discovery"},
    {"name": "feroxbuster", "family": "web", "summary": "Recursive content discovery fallback"},
    {"name": "gobuster", "family": "web", "summary": "Directory and vhost enumeration fallback"},
    {"name": "nikto", "family": "web", "summary": "Quick web misconfiguration checks"},
    {"name": "nuclei", "family": "web", "summary": "Template-driven web checks"},
    {"name": "whatweb", "family": "web", "summary": "Web technology fingerprinting"},
    {"name": "smbclient", "family": "windows", "summary": "Anonymous share listing and access"},
    {"name": "smbmap", "family": "windows", "summary": "Share permissions and content checks"},
    {"name": "enum4linux-ng", "family": "windows", "summary": "SMB and RPC enumeration"},
    {"name": "rpcclient", "family": "windows", "summary": "RPC user and domain interrogation"},
    {"name": "netexec", "family": "windows", "summary": "Credential validation and lateral checks"},
    {"name": "crackmapexec", "family": "windows", "summary": "Credential validation fallback"},
    {"name": "impacket-psexec", "family": "windows", "summary": "Remote execution with valid creds"},
    {"name": "impacket-wmiexec", "family": "windows", "summary": "WMI execution with valid creds"},
    {"name": "ldapsearch", "family": "windows", "summary": "LDAP enumeration"},
    {"name": "kerbrute", "family": "windows", "summary": "Kerberos user checks"},
    {"name": "dig", "family": "infra", "summary": "DNS interrogation"},
    {"name": "ftp", "family": "auth", "summary": "FTP access validation"},
    {"name": "snmpwalk", "family": "infra", "summary": "SNMP enumeration"},
    {"name": "hydra", "family": "auth", "summary": "Bounded credential validation"},
]

DEFAULT_COMMAND_ALLOWLIST = {
    "curl",
    "dirb",
    "enum4linux",
    "ffuf",
    "gobuster",
    "nikto",
    "nmap",
    "smbclient",
    "whatweb",
    "wget",
}
DEFAULT_LLM_SETTINGS = {
    "ollama_base_url": OLLAMA_BASE_URL or None,
    "ollama_tailscale_host": OLLAMA_TAILSCALE_HOST or None,
    "ollama_timeout_seconds": OLLAMA_TIMEOUT_SECONDS,
    "default_model": "llama3.2:3b",
    "temperature": 0.2,
    "num_ctx": 8192,
    "autoplan_enabled": False,
    "autoplan_interval_seconds": PLANNER_INTERVAL_SECONDS,
    "autoplan_max_actions_per_turn": 4,
    "autoplan_include_timeline": True,
    "autoplan_include_execution_history": True,
    "autoplan_prompt": (
        "Continue autonomously using the HTB methodology. Feed in the prior jobs, actions, "
        "results, and pending queue. Propose only the next smallest useful approval-gated terminal "
        "actions. Do not repeat commands that already failed unless the command is corrected and "
        "the correction is explicit. Do not invent local wordlist paths; if a needed file path is "
        "unknown, first propose a small discovery command. Return concise reasoning and a JSON "
        "object with proposed_actions, where each action has label, command, reason, risk, stage, and parser."
    ),
    "system_prompt": None,
    "command_allowlist": sorted(DEFAULT_COMMAND_ALLOWLIST),
    "autonomy_profile": "through_privesc",
    "autonomy_pause_on_credential": True,
    "autonomy_pause_on_session": True,
    "autonomy_pause_on_privesc": True,
    "autonomy_max_noise": "high",
}

STATE_LOCK = threading.Lock()
RUNTIME_LOCK = threading.Lock()
EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="htbmc")
EXECUTION_RUNTIME: dict[str, dict[str, Any]] = {}
SHELL_SESSION_TOKENS: dict[str, dict[str, Any]] = {}
LIVE_OUTPUT_TAIL_LIMIT = 12000
LIVE_EVENT_LIMIT = 120
PROCESS_STOP_WAIT_SECONDS = 5
SHELL_TOKEN_TTL_SECONDS = 120
PLANNER_STOP_EVENT = threading.Event()
PLANNER_THREAD: threading.Thread | None = None
PLANNER_RUNTIME_LOCK = threading.Lock()
PLANNER_LLM_TOKEN_BUCKET = float(PLANNER_GLOBAL_RPM)
PLANNER_LLM_LAST_REFILL = time.monotonic()
PLANNER_LLM_INFLIGHT = 0
PLANNER_TARGET_LAST_LLM_AT: dict[str, float] = {}


class _PlannerLlmPermit:
    def __init__(self, target_id: str | None):
        self.target_id = target_id or "unknown"

    def __enter__(self) -> "_PlannerLlmPermit":
        _enforce_planner_llm_limits(self.target_id)
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        _release_planner_llm_inflight()


class TargetInput(BaseModel):
    ip_address: str | None = Field(default=None, min_length=2, max_length=45)
    ip: str | None = Field(default=None, min_length=2, max_length=45)
    label: str | None = Field(default=None, max_length=120)
    start_enumeration: bool = False

    @model_validator(mode="after")
    def validate_ip_fields(self) -> "TargetInput":
        if not (self.ip_address or self.ip):
            raise ValueError("ip_address is required")
        return self

    def resolved_ip(self) -> str:
        return (self.ip_address or self.ip or "").strip()


class LlmPromptRequest(BaseModel):
    ip_address: str | None = Field(default=None, min_length=7, max_length=45)
    target_id: str | None = Field(default=None, min_length=8, max_length=32)
    prompt: str = Field(min_length=1, max_length=4000)
    model: str = Field(default="auto", max_length=120)
    context_block_ids: list[str] = Field(default_factory=list)
    include_services: bool = True
    include_findings: bool = True
    include_observations: bool = True
    include_pending_actions: bool = True
    include_timeline: bool = False

    @model_validator(mode="after")
    def validate_target_fields(self) -> "LlmPromptRequest":
        if not (self.target_id or self.ip_address):
            raise ValueError("target_id or ip_address is required")
        return self


class ContextBlockInput(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    content: str = Field(min_length=1, max_length=20000)
    kind: str = Field(default="notes", min_length=2, max_length=40)


class ActionDecisionRequest(BaseModel):
    note: str | None = Field(default=None, max_length=600)


class ShellSessionInput(BaseModel):
    protocol: str = Field(default="ssh", pattern="^(ssh|telnet|nc)$")
    host: str | None = Field(default=None, min_length=2, max_length=255)
    port: int = Field(default=22, ge=1, le=65535)
    username: str | None = Field(default=None, max_length=128)
    password: str | None = Field(default=None, max_length=512)
    label: str | None = Field(default=None, max_length=160)
    cols: int = Field(default=100, ge=20, le=300)
    rows: int = Field(default=32, ge=8, le=120)


class LlmSettingsInput(BaseModel):
    ollama_base_url: str | None = Field(default=None, max_length=300)
    ollama_tailscale_host: str | None = Field(default=None, max_length=120)
    ollama_timeout_seconds: float = Field(default=5.0, ge=1, le=180)
    default_model: str = Field(default="auto", max_length=120)
    temperature: float = Field(default=0.2, ge=0, le=2)
    num_ctx: int = Field(default=8192, ge=1024, le=65536)
    autoplan_enabled: bool = False
    autoplan_interval_seconds: int = Field(default=20, ge=5, le=3600)
    autoplan_max_actions_per_turn: int = Field(default=4, ge=1, le=10)
    autoplan_include_timeline: bool = True
    autoplan_include_execution_history: bool = True
    autoplan_prompt: str = Field(default="", max_length=4000)
    system_prompt: str | None = Field(default=None, max_length=8000)
    command_allowlist: list[str] | None = None
    autonomy_profile: str = Field(default="through_privesc", pattern="^(recon_only|through_foothold|through_privesc)$")
    autonomy_pause_on_credential: bool = True
    autonomy_pause_on_session: bool = True
    autonomy_pause_on_privesc: bool = True
    autonomy_max_noise: str = Field(default="high", pattern="^(safe|low|medium|high)$")


class AutonomyProfileInput(BaseModel):
    profile: str = Field(pattern="^(recon_only|through_foothold|through_privesc)$")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def _ensure_dirs() -> None:
    TARGETS_DIR.mkdir(parents=True, exist_ok=True)
    SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
    LLM_PROMPTS_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)


def _clear_past_runs() -> None:
    for directory in (TARGETS_DIR, STATE_DIR / "projects"):
        if not directory.exists():
            continue
        for item in directory.iterdir():
            if item.is_dir():
                shutil.rmtree(item, ignore_errors=True)
            else:
                item.unlink(missing_ok=True)


def _normalize_command_allowlist(commands: list[str] | None) -> list[str]:
    if not isinstance(commands, list):
        return sorted(DEFAULT_COMMAND_ALLOWLIST)
    cleaned = {
        item.strip().lower()
        for item in commands
        if isinstance(item, str) and re.fullmatch(r"[a-z0-9][a-z0-9._+-]*", item.strip().lower())
    }
    return sorted(cleaned or DEFAULT_COMMAND_ALLOWLIST)


def _runtime_settings() -> dict[str, Any]:
    settings = dict(DEFAULT_LLM_SETTINGS)
    if RUNTIME_SETTINGS_PATH.exists():
        persisted = _read_json(RUNTIME_SETTINGS_PATH)
        if isinstance(persisted, dict):
            settings.update({key: value for key, value in persisted.items() if value is not None})
    settings["command_allowlist"] = _normalize_command_allowlist(settings.get("command_allowlist"))
    return settings


def _save_runtime_settings(settings: dict[str, Any]) -> dict[str, Any]:
    merged = dict(DEFAULT_LLM_SETTINGS)
    if RUNTIME_SETTINGS_PATH.exists():
        persisted = _read_json(RUNTIME_SETTINGS_PATH)
        if isinstance(persisted, dict):
            merged.update(persisted)
    merged.update(settings)
    merged["command_allowlist"] = _normalize_command_allowlist(merged.get("command_allowlist"))
    _write_json(RUNTIME_SETTINGS_PATH, merged)
    _apply_runtime_settings(merged)
    return merged


def _apply_runtime_settings(settings: dict[str, Any]) -> None:
    global OLLAMA_BASE_URL, OLLAMA_TAILSCALE_HOST, OLLAMA_TIMEOUT_SECONDS
    global PLANNER_INTERVAL_SECONDS
    OLLAMA_BASE_URL = str(settings.get("ollama_base_url") or "").strip()
    OLLAMA_TAILSCALE_HOST = str(settings.get("ollama_tailscale_host") or "").strip()
    OLLAMA_TIMEOUT_SECONDS = float(settings.get("ollama_timeout_seconds") or DEFAULT_LLM_SETTINGS["ollama_timeout_seconds"])
    PLANNER_INTERVAL_SECONDS = max(5.0, float(settings.get("autoplan_interval_seconds") or DEFAULT_LLM_SETTINGS["autoplan_interval_seconds"]))


def _command_allowlist() -> set[str]:
    return set(_runtime_settings().get("command_allowlist") or DEFAULT_COMMAND_ALLOWLIST)


def _command_is_allowlisted(command: str) -> bool:
    binary = _binary_for_command(command)
    return binary.lower() in _command_allowlist()


def _command_looks_like_install(command: str) -> bool:
    text = command.lower()
    return bool(
        re.search(r"\b(apt|apt-get|apk|yum|dnf|brew|pip3?|npm|pnpm|yarn|gem)\s+(?:.*\s)?install\b", text)
        or re.search(r"\binstall(?:ing|ation)?\b", text)
    )


def _command_is_dangerous(command: str) -> bool:
    text = command.lower()
    direct_patterns = [
        r"\brm\b",
        r"\bdel\b",
        r"\bmv\b",
        r"\bchmod\b",
        r"\bchown\b",
        r"\bhydra\b",
        r"\bmedusa\b",
        r"\bmsfconsole\b",
        r"\bmsfvenom\b",
        r"\bsqlmap\b",
        r"\bnc\s+-e\b",
        r"\bbash\s+-i\b",
        r"\bpython\s+-c\b",
        r"\bperl\s+-e\b",
    ]
    return any(re.search(pattern, text) for pattern in direct_patterns)


def _default_llm_agent_state() -> dict[str, Any]:
    return {
        "enabled": False,
        "last_prompt_at": None,
        "last_response_at": None,
        "last_queued_action_ids": [],
    }


def _default_autonomy_state() -> dict[str, Any]:
    runtime = _runtime_settings()
    return {
        "profile": runtime.get("autonomy_profile", "through_privesc"),
        "paused": False,
        "pause_reason": None,
        "paused_at": None,
        "pause_on_credential": bool(runtime.get("autonomy_pause_on_credential", True)),
        "pause_on_session": bool(runtime.get("autonomy_pause_on_session", True)),
        "pause_on_privesc": bool(runtime.get("autonomy_pause_on_privesc", True)),
        "max_noise": runtime.get("autonomy_max_noise", "high"),
        "last_decision_at": None,
        "last_selected_path_id": None,
    }


def _default_objectives() -> dict[str, Any]:
    return {
        "current_phase": "recon",
        "states": {
            "recon": "active",
            "cred-hunting": "pending",
            "initial-access": "pending",
            "post-access": "pending",
            "privesc": "pending",
            "owned": "pending",
        },
    }


def _default_host_records(ip_address: str) -> list[dict[str, Any]]:
    return [
        {
            "id": f"host_{uuid.uuid4().hex[:8]}",
            "address": ip_address,
            "role": "target",
            "source": "target_record",
            "created_at": _now(),
        }
    ]


def _default_attack_graph(ip_address: str) -> dict[str, Any]:
    return {
        "nodes": [
            {
                "id": f"host:{ip_address}",
                "kind": "host",
                "label": ip_address,
                "status": "known",
            }
        ],
        "edges": [],
        "summary": "Target created. Enumeration has not started yet.",
    }


def _planner_log(event_type: str, message: str, data: dict[str, Any] | None = None) -> None:
    _append_jsonl(
        PLANNER_LOG_PATH,
        {
            "timestamp_utc": _now(),
            "event_type": event_type,
            "message": message,
            "data": data or {},
        },
    )


def _failure_retry_prompt(target: dict[str, Any], item_kind: str, item: dict[str, Any]) -> str:
    summary = {
        "target_id": target.get("id"),
        "ip_address": target.get("ip_address"),
        "item_kind": item_kind,
        "label": item.get("label"),
        "command": item.get("command"),
        "return_code": item.get("return_code"),
        "error": str(item.get("error") or "")[:1200],
        "output_tail": str(item.get("live_output_tail") or "")[:1200],
    }
    prompt = (
        "A prior mission-control command failed. Never repeat the exact failed command unless the "
        "correction is explicit and minimal. Use the failure details below to propose a corrected "
        "next step only if there is a concrete fix.\n\n"
        f"{json.dumps(summary, indent=2)}"
    )
    return prompt[:4000]


def _auto_approve_allowlisted_actions(target: dict[str, Any]) -> bool:
    changed = False
    for action in target.get("agent_actions", []):
        if action.get("status") not in {"pending_approval", "blocked"}:
            continue
        command = str(action.get("command") or "")
        if not command or not action.get("tool_available", True):
            continue
        if not _command_is_allowlisted(command):
            continue
        if _command_looks_like_install(command) or _command_is_dangerous(command):
            continue
        action["status"] = "approved"
        action["approved_at"] = _now()
        action["updated_at"] = _now()
        action["auto_approved"] = True
        changed = True
    return changed


def _validate_ip(ip_address: str) -> str:
    try:
        return str(ipaddress.ip_address(ip_address))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid IP address") from exc


def _target_dir(target_id: str) -> Path:
    return TARGETS_DIR / target_id


def _target_file(target_id: str) -> Path:
    return _target_dir(target_id) / "target.json"


def _logs_dir(target_id: str) -> Path:
    return _target_dir(target_id) / "logs"


def _activity_log_path(target_id: str) -> Path:
    return _logs_dir(target_id) / "activity.jsonl"


def _llm_prompts_log_path() -> Path:
    return LLM_PROMPTS_LOG_PATH


def _artifacts_dir(target_id: str, category: str) -> Path:
    return _target_dir(target_id) / "artifacts" / category


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    tmp_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp_path.replace(path)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _tail_text_from_path(path: str | None, limit: int = LIVE_OUTPUT_TAIL_LIMIT) -> str:
    if not path:
        return ""
    file_path = Path(path)
    if not file_path.exists() or not file_path.is_file():
        return ""
    try:
        text = file_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return text[-limit:]


def _append_jsonl(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(data) + "\n")


def _normalize_target(target: dict[str, Any]) -> dict[str, Any]:
    changed = False
    defaults = {
        "schema_version": STATE_SCHEMA_VERSION,
        "hostnames": [],
        "findings": [],
        "agent_actions": [],
        "observations": [],
        "context_blocks": [],
        "conversation": [],
        "llm_calls": [],
        "credentials": [],
        "sessions": [],
        "artifacts": [],
        "paths": [],
        "objectives": _default_objectives(),
        "hosts": _default_host_records(target["ip_address"]),
        "web_surfaces": [],
        "attack_graph": _default_attack_graph(target["ip_address"]),
        "best_path": None,
        "decision_journal": [],
        "autonomy": _default_autonomy_state(),
        "llm_agent": _default_llm_agent_state(),
        "recommendations": _default_recommendations(target["ip_address"]),
    }
    for key, value in defaults.items():
        if key not in target or target[key] is None:
            target[key] = value
            changed = True
    for action in target.get("agent_actions", []):
        for key, value in {
            "pid": None,
            "output_bytes": 0,
            "last_output_at": None,
            "live_output_tail": "",
            "stop_requested_at": None,
            "termination_reason": None,
            "stage": "general",
            "priority": 50,
            "source": "playbook",
            "mindset": None,
            "requires": [],
            "produces": [],
            "confidence": "candidate",
            "noise_level": "low",
            "stop_on_success": False,
            "campaign": "general",
        }.items():
            if key not in action:
                action[key] = value
                changed = True
        if "tool_available" not in action:
            action["tool_available"] = True
            changed = True
        if "auto_approved" not in action:
            action["auto_approved"] = False
            changed = True
        approved_at = _parse_timestamp(action.get("approved_at"))
        if (
            action.get("status") == "approved"
            and not action.get("started_at")
            and approved_at is not None
            and (datetime.now(timezone.utc) - approved_at).total_seconds() > 15
        ):
            action["status"] = "pending_approval"
            action["updated_at"] = _now()
            action["error"] = "Approved action did not start and was returned to the approval queue."
            changed = True
    for job in target.get("jobs", []):
        for key, value in {
            "pid": None,
            "output_bytes": 0,
            "last_output_at": None,
            "live_output_tail": "",
            "stop_requested_at": None,
            "termination_reason": None,
        }.items():
            if key not in job:
                job[key] = value
                changed = True
        started_at = _parse_timestamp(job.get("started_at") or job.get("created_at"))
        if (
            job.get("status") in {"queued", "running", "stopping"}
            and _get_execution_runtime("job", job.get("id", "")) is None
            and started_at is not None
            and (datetime.now(timezone.utc) - started_at).total_seconds() > 15
        ):
            job["finished_at"] = job.get("finished_at") or _now()
            job["updated_at"] = _now()
            job["termination_reason"] = job.get("termination_reason") or "recovered_stale_runtime"
            if target.get("services"):
                job["status"] = "completed"
                job["return_code"] = 0 if job.get("return_code") is None else job.get("return_code")
                job["summary"] = job.get("summary") or f"Recovered historical scan record with {len(target.get('services', []))} parsed services."
                job["error"] = None
            else:
                job["status"] = "failed"
                job["error"] = job.get("error") or "Execution runtime was lost before results were preserved."
                job["summary"] = job.get("summary") or "Recovered a stale execution record without parsed services."
            changed = True
    for llm_call in target.get("llm_calls", []):
        response_text = str(llm_call.get("response_text") or llm_call.get("live_output_tail") or "")
        for key, value in {
            "kind": "operator",
            "status": "completed",
            "title": "LLM request",
            "detail": "",
            "model": None,
            "request_messages": [],
            "operator_prompt": None,
            "response_text": response_text,
            "live_output_tail": response_text,
            "output_bytes": len(response_text.encode("utf-8")),
            "last_output_at": llm_call.get("finished_at") or llm_call.get("updated_at"),
            "prompt_id": llm_call.get("id"),
            "message_id": None,
            "queued_action_ids": [],
            "attached_context": {},
            "model_error": None,
            "summary": None,
            "result_excerpt": response_text[:1200],
            "error": None,
            "pid": None,
            "stop_requested_at": None,
            "termination_reason": None,
        }.items():
            if key not in llm_call:
                llm_call[key] = value
                changed = True
    if _migrate_action_metadata(target):
        changed = True
    if target.get("services"):
        action_snapshot = json.dumps(target.get("agent_actions", []), sort_keys=True)
        recommendation_snapshot = json.dumps(target.get("recommendations", []), sort_keys=True)
        _refresh_agent_actions(target)
        if (
            action_snapshot != json.dumps(target.get("agent_actions", []), sort_keys=True)
            or recommendation_snapshot != json.dumps(target.get("recommendations", []), sort_keys=True)
        ):
            changed = True
        findings_snapshot = json.dumps(target.get("findings", []), sort_keys=True)
        target["findings"] = _build_findings(target.get("services", []), target.get("observations", []))
        if findings_snapshot != json.dumps(target.get("findings", []), sort_keys=True):
            changed = True
        summary_snapshot = target.get("latest_summary")
        target["latest_summary"] = _compose_summary(target)
        if summary_snapshot != target.get("latest_summary"):
            changed = True
    if not target.get("web_surfaces") and target.get("services"):
        changed = True
    graph_snapshot = json.dumps(target.get("attack_graph", {}), sort_keys=True)
    best_path_snapshot = json.dumps(target.get("best_path"), sort_keys=True)
    objective_snapshot = json.dumps(target.get("objectives", {}), sort_keys=True)
    _rebuild_attack_state(target)
    if (
        graph_snapshot != json.dumps(target.get("attack_graph", {}), sort_keys=True)
        or best_path_snapshot != json.dumps(target.get("best_path"), sort_keys=True)
        or objective_snapshot != json.dumps(target.get("objectives", {}), sort_keys=True)
    ):
        changed = True
    retrofit_snapshot = json.dumps(
        {
            "credentials": target.get("credentials", []),
            "sessions": target.get("sessions", []),
            "web_surfaces": target.get("web_surfaces", []),
            "paths": target.get("paths", []),
        },
        sort_keys=True,
    )
    _retrofit_observed_intelligence(target)
    retrofit_changed = retrofit_snapshot != json.dumps(
        {
            "credentials": target.get("credentials", []),
            "sessions": target.get("sessions", []),
            "web_surfaces": target.get("web_surfaces", []),
            "paths": target.get("paths", []),
        },
        sort_keys=True,
    )
    if retrofit_changed:
        _rebuild_attack_state(target)
        changed = True
    if not _job_is_active(target) and not _action_is_active(target):
        resting_phase = _resting_target_phase(target)
        if target.get("phase") != resting_phase and target.get("phase") not in {"initial_enumeration"}:
            target["phase"] = resting_phase
            changed = True
    if not _job_is_active(target) and target.get("status") == "enumerating":
        target["status"] = "ready" if target.get("phase") != "enumeration_failed" else "error"
        changed = True
    return target if not changed else _save_target(target)


def _load_target(target_id: str) -> dict[str, Any]:
    path = _target_file(target_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Target not found")
    return _normalize_target(_read_json(path))


def _save_target(target: dict[str, Any]) -> dict[str, Any]:
    target["updated_at"] = _now()
    _write_json(_target_file(target["id"]), target)
    return target


def _with_target_lock(target_id: str, mutator) -> dict[str, Any]:
    with STATE_LOCK:
        target = _load_target(target_id)
        mutator(target)
        saved = _save_target(target)
    return saved


def _timeline_event(event_type: str, message: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "id": _new_id("evt"),
        "type": event_type,
        "message": message,
        "data": data or {},
        "timestamp_utc": _now(),
    }


def _log_activity(target_id: str, event_type: str, message: str, data: dict[str, Any] | None = None) -> None:
    _append_jsonl(
        _activity_log_path(target_id),
        {
            "timestamp_utc": _now(),
            "event_type": event_type,
            "message": message,
            "data": data or {},
        },
    )


def _append_decision_journal(target: dict[str, Any], title: str, summary: str, **data: Any) -> dict[str, Any]:
    entry = {
        "id": _new_id("jrnl"),
        "title": title,
        "summary": summary,
        "timestamp_utc": _now(),
        **data,
    }
    target.setdefault("decision_journal", []).append(entry)
    return entry


def _entity_exists(items: list[dict[str, Any]], key: str, value: str) -> bool:
    return any(str(item.get(key) or "").strip().lower() == value.strip().lower() for item in items)


def _current_objective_phase(target: dict[str, Any]) -> str:
    return str((target.get("objectives") or {}).get("current_phase") or "recon")


def _set_objective_phase(target: dict[str, Any], phase: str) -> None:
    objectives = target.setdefault("objectives", _default_objectives())
    phase_order = ["recon", "cred-hunting", "initial-access", "post-access", "privesc", "owned"]
    objectives["current_phase"] = phase
    for item in phase_order:
        if item == phase:
            objectives["states"][item] = "active"
        elif phase_order.index(item) < phase_order.index(phase):
            objectives["states"][item] = "completed"
        elif objectives["states"].get(item) != "completed":
            objectives["states"][item] = "pending"


def _target_capabilities(target: dict[str, Any]) -> set[str]:
    capabilities = {"target"}
    if target.get("services"):
        capabilities.add("services")
    if any(int(service.get("port") or 0) in {80, 443, 8000, 8080, 8443} for service in target.get("services", [])):
        capabilities.add("web_surface")
    if any(int(service.get("port") or 0) in {139, 445} for service in target.get("services", [])):
        capabilities.add("smb")
    if any(int(service.get("port") or 0) == 53 for service in target.get("services", [])):
        capabilities.add("dns")
    if any(int(service.get("port") or 0) == 21 for service in target.get("services", [])):
        capabilities.add("ftp")
    if any(int(service.get("port") or 0) in {389, 636} for service in target.get("services", [])):
        capabilities.add("ldap")
    if any(int(service.get("port") or 0) in {161} for service in target.get("services", [])):
        capabilities.add("snmp")
    if target.get("credentials"):
        capabilities.add("credentials")
    if target.get("sessions"):
        capabilities.add("session")
        capabilities.add("post_access")
    if any(item.get("kind") == "privesc_signal" for item in target.get("paths", [])):
        capabilities.add("privesc_signal")
    return capabilities


def _profile_allows_stage(profile: str, stage: str) -> bool:
    stage_level = STAGE_CAPABILITY_ORDER.get(stage, 0)
    return AUTONOMY_PROFILE_ORDER.get(profile, AUTONOMY_PROFILE_ORDER["through_privesc"]) >= stage_level


def _action_policy_verdict(target: dict[str, Any], template: dict[str, Any]) -> tuple[bool, str | None]:
    autonomy = target.get("autonomy") or _default_autonomy_state()
    if autonomy.get("paused"):
        return False, f"Autonomy paused: {autonomy.get('pause_reason') or 'manual pause'}"
    required = set(template.get("requires") or [])
    missing = sorted(required - _target_capabilities(target))
    if missing:
        return False, f"Missing prerequisites: {', '.join(missing)}"
    profile = str(autonomy.get("profile") or "through_privesc")
    if not _profile_allows_stage(profile, str(template.get("stage") or "general")):
        return False, f"Autonomy profile {profile} does not allow stage {template.get('stage')}"
    max_noise = str(autonomy.get("max_noise") or "high")
    template_noise = str(template.get("noise_level") or "low")
    if NOISE_LEVEL_ORDER.get(template_noise, 1) > NOISE_LEVEL_ORDER.get(max_noise, 3):
        return False, f"Noise level {template_noise} exceeds autonomy threshold {max_noise}"
    return True, None


def _tool_catalog_payload() -> dict[str, Any]:
    return {
        "generated_at": _now(),
        "tools": [
            {
                **item,
                "installed": _tool_available(item["name"]),
                "path": shutil.which(item["name"]),
            }
            for item in TOOL_CATALOG
        ],
    }


def _rebuild_attack_state(target: dict[str, Any]) -> None:
    ip_address = target["ip_address"]
    host_id = f"host:{ip_address}"
    nodes: list[dict[str, Any]] = [{"id": host_id, "kind": "host", "label": ip_address, "status": "known"}]
    edges: list[dict[str, Any]] = []
    services = target.get("services", [])
    findings = target.get("findings", [])
    credentials = target.get("credentials", [])
    sessions = target.get("sessions", [])
    web_surfaces = target.get("web_surfaces", [])
    paths = target.get("paths", [])

    for service in services:
        service_id = f"service:{service.get('protocol')}:{service.get('port')}"
        label = f"{service.get('port')}/{service.get('protocol')} {service.get('service')}"
        nodes.append({"id": service_id, "kind": "service", "label": label, "status": "open"})
        edges.append({"source": host_id, "target": service_id, "relation": "exposes"})
    for finding in findings[:12]:
        finding_id = finding.get("id") or _new_id("finding")
        nodes.append({"id": finding_id, "kind": "finding", "label": finding.get("title") or "Finding", "status": finding.get("severity", "info")})
        if finding.get("port") is not None:
            edges.append({"source": f"service:tcp:{finding.get('port')}", "target": finding_id, "relation": "suggests"})
    for surface in web_surfaces:
        surface_id = surface.get("id") or f"web:{surface.get('url')}"
        nodes.append({"id": surface_id, "kind": "web_surface", "label": surface.get("label") or surface.get("url"), "status": surface.get("status", "known")})
        edges.append({"source": host_id, "target": surface_id, "relation": "hosts"})
    for cred in credentials:
        cred_id = cred.get("id") or _new_id("cred")
        nodes.append({"id": cred_id, "kind": "credential", "label": cred.get("label") or cred.get("username") or "credential", "status": cred.get("status", "candidate")})
        source_finding = cred.get("source_finding_id")
        if source_finding:
            edges.append({"source": source_finding, "target": cred_id, "relation": "yields"})
    for session in sessions:
        session_id = session.get("id") or _new_id("sess")
        nodes.append({"id": session_id, "kind": "session", "label": session.get("label") or session.get("user") or "session", "status": session.get("status", "active")})
        if session.get("credential_id"):
            edges.append({"source": session.get("credential_id"), "target": session_id, "relation": "authenticates"})
        else:
            edges.append({"source": host_id, "target": session_id, "relation": "owns"})
    for path in paths[-12:]:
        path_id = path.get("id") or _new_id("path")
        nodes.append({"id": path_id, "kind": "path", "label": path.get("label") or path.get("kind") or "path", "status": path.get("status", "candidate")})
        if path.get("from_id") and path.get("to_id"):
            edges.append({"source": path["from_id"], "target": path["to_id"], "relation": path.get("kind", "path"), "path_id": path_id})

    if sessions:
        _set_objective_phase(target, "post-access")
    elif credentials:
        _set_objective_phase(target, "initial-access")
    elif services:
        if any(service.get("service") in {"http", "https", "microsoft-ds", "ldap"} for service in services):
            _set_objective_phase(target, "cred-hunting")
        else:
            _set_objective_phase(target, "recon")
    else:
        _set_objective_phase(target, "recon")

    best_path = None
    if sessions:
        latest_session = sessions[-1]
        best_path = {
            "id": f"path_best_{latest_session.get('id', 'session')}",
            "label": f"Operate through {latest_session.get('label') or latest_session.get('user') or 'active session'}",
            "confidence": latest_session.get("confidence", "observed"),
            "why": latest_session.get("summary") or "A live session exists, so post-access work is now the highest-value path.",
            "next_objective": "privesc",
        }
    elif credentials:
        latest_cred = credentials[-1]
        best_path = {
            "id": f"path_best_{latest_cred.get('id', 'credential')}",
            "label": f"Validate {latest_cred.get('username') or latest_cred.get('label') or 'credential'}",
            "confidence": latest_cred.get("confidence", "candidate"),
            "why": latest_cred.get("summary") or "Stored credentials now justify a bounded access attempt.",
            "next_objective": "initial-access",
        }
    elif web_surfaces:
        latest_surface = web_surfaces[-1]
        best_path = {
            "id": f"path_best_{latest_surface.get('id', 'web')}",
            "label": f"Deepen web enumeration on {latest_surface.get('url')}",
            "confidence": latest_surface.get("confidence", "observed"),
            "why": latest_surface.get("summary") or "A web surface is available for targeted discovery and validation.",
            "next_objective": "cred-hunting",
        }
    elif services:
        first_service = services[0]
        best_path = {
            "id": f"path_best_service_{first_service.get('port')}",
            "label": f"Deepen {first_service.get('service')} on {first_service.get('port')}",
            "confidence": "observed",
            "why": "Baseline enumeration completed and the first exposed service still needs deeper playbook coverage.",
            "next_objective": "cred-hunting",
        }

    target["attack_graph"] = {
        "nodes": nodes,
        "edges": edges,
        "summary": target.get("latest_summary") or "Attack graph rebuilt from stored evidence.",
    }
    target["best_path"] = best_path


def _target_summary(target: dict[str, Any]) -> dict[str, Any]:
    latest_job = target["jobs"][-1] if target["jobs"] else None
    services = target.get("services", [])
    actions = target.get("agent_actions", [])
    return {
        "id": target["id"],
        "ip_address": target["ip_address"],
        "label": target.get("label"),
        "display_name": target.get("display_name"),
        "status": target.get("status"),
        "phase": target.get("phase"),
        "created_at": target.get("created_at"),
        "updated_at": target.get("updated_at"),
        "open_ports": len(services),
        "latest_job_status": latest_job.get("status") if latest_job else "idle",
        "latest_summary": target.get("latest_summary", ""),
        "pending_actions": len([item for item in actions if item["status"] in {"pending_approval", "blocked"}]),
        "objective_phase": _current_objective_phase(target),
        "credential_count": len(target.get("credentials", [])),
        "session_count": len(target.get("sessions", [])),
        "autonomy_paused": bool((target.get("autonomy") or {}).get("paused")),
    }


def _list_targets() -> list[dict[str, Any]]:
    _ensure_dirs()
    targets: list[dict[str, Any]] = []
    for case_dir in TARGETS_DIR.iterdir():
        target_path = case_dir / "target.json"
        if target_path.exists():
            target = _normalize_target(_read_json(target_path))
            if not _action_is_active(target) and any(item.get("status") == "approved" for item in target.get("agent_actions", [])):
                _dispatch_next_approved_action(target["id"])
                target = _load_target(target["id"])
            targets.append(_target_summary(target))
    targets.sort(key=lambda item: item["updated_at"], reverse=True)
    return targets


def _tool_available(binary: str) -> bool:
    return shutil.which(binary) is not None


def _find_target_by_ip(ip_address: str) -> dict[str, Any] | None:
    for target_summary in _list_targets():
        if target_summary["ip_address"] == ip_address:
            return _load_target(target_summary["id"])
    return None


def _find_target(target_id: str | None = None, ip_address: str | None = None) -> dict[str, Any] | None:
    if target_id:
        return _load_target(target_id)
    if ip_address:
        return _find_target_by_ip(ip_address)
    return None


def _word_count(value: str) -> int:
    return len(re.findall(r"\S+", value or ""))


def _target_knowledge_text(target: dict[str, Any]) -> str:
    chunks = [target.get("latest_summary", "")]
    chunks.extend(item.get("summary", "") for item in target.get("observations", []))
    chunks.extend(item.get("summary", "") for item in target.get("agent_actions", []) if item.get("summary"))
    chunks.extend(item.get("result_excerpt", "") for item in target.get("agent_actions", []) if item.get("result_excerpt"))
    return "\n".join(chunk for chunk in chunks if chunk).lower()


def _target_credential_text(target: dict[str, Any]) -> str:
    chunks: list[str] = []
    chunks.extend(f"{item.get('title', '')} {item.get('summary', '')}" for item in target.get("observations", []))
    chunks.extend(f"{item.get('label', '')} {item.get('summary', '')} {item.get('result_excerpt', '')}" for item in target.get("agent_actions", []))
    chunks.extend(f"{item.get('title', '')} {item.get('content', '')}" for item in target.get("context_blocks", []))
    return "\n".join(chunk for chunk in chunks if chunk)


def _credential_hints_from_target(target: dict[str, Any]) -> dict[str, Any]:
    text = _target_credential_text(target)
    usernames = [
        match.group(1)
        for match in re.finditer(r"(?:user(?:name)?|login)\s*[:=]\s*([A-Za-z0-9._@-]{2,})", text, re.IGNORECASE)
    ]
    passwords = [
        match.group(1)
        for match in re.finditer(r"(?:pass(?:word)?|pwd)\s*[:=]\s*([^\s'\"<>]{3,})", text, re.IGNORECASE)
    ]
    pairs = [
        {"username": match.group(1), "password": match.group(2)}
        for match in re.finditer(
            r"(?:creds?|credentials?|login)\s*[:=]\s*([A-Za-z0-9._@-]{2,})\s*(?:/|:|\s+)\s*([^\s'\"<>]{3,})",
            text,
            re.IGNORECASE,
        )
    ]
    if usernames and passwords:
        pairs.extend({"username": username, "password": password} for username in usernames[:4] for password in passwords[:4])

    seen_pairs: set[tuple[str, str]] = set()
    unique_pairs: list[dict[str, str]] = []
    for pair in pairs:
        key = (pair["username"], pair["password"])
        if key in seen_pairs:
            continue
        seen_pairs.add(key)
        unique_pairs.append(pair)

    return {
        "usernames": sorted(set(usernames))[:12],
        "passwords": sorted(set(passwords))[:12],
        "pairs": unique_pairs[:12],
    }


def _shell_service_candidates(target: dict[str, Any]) -> list[dict[str, Any]]:
    credentials = _credential_hints_from_target(target)
    candidates: list[dict[str, Any]] = []
    ip_address = target["ip_address"]
    for service in target.get("services", []):
        port = int(service.get("port") or 0)
        service_name = str(service.get("service") or "").lower()
        detail = str(service.get("detail") or "").lower()
        if not port:
            continue
        if service_name == "ssh" or port == 22:
            pairs = credentials["pairs"] or [{"username": "", "password": ""}]
            for pair in pairs[:6]:
                username = pair.get("username") or ""
                candidates.append(
                    {
                        "id": f"ssh-{port}-{username or 'manual'}",
                        "protocol": "ssh",
                        "host": ip_address,
                        "port": port,
                        "username": username,
                        "password": pair.get("password") or "",
                        "has_password": bool(pair.get("password")),
                        "label": f"SSH {username + '@' if username else ''}{ip_address}:{port}",
                        "source": "credential_hints" if pair.get("password") else "open_service",
                    }
                )
        if service_name == "telnet" or port == 23:
            candidates.append(
                {
                    "id": f"telnet-{port}",
                    "protocol": "telnet",
                    "host": ip_address,
                    "port": port,
                    "username": "",
                    "has_password": False,
                    "label": f"Telnet {ip_address}:{port}",
                    "source": "open_service",
                }
            )
        if port in {1524, 4444, 4445, 5555, 6200} or "shell" in service_name or "shell" in detail or "backdoor" in detail:
            candidates.append(
                {
                    "id": f"nc-{port}",
                    "protocol": "nc",
                    "host": ip_address,
                    "port": port,
                    "username": "",
                    "has_password": False,
                    "label": f"Raw shell {ip_address}:{port}",
                    "source": "shell_service",
                }
            )
    return candidates


def _has_action_in_state(target: dict[str, Any], category: str, statuses: set[str] | None = None) -> bool:
    desired_statuses = statuses or {
        "pending_approval",
        "blocked",
        "approved",
        "running",
        "stopping",
        "completed",
        "informational",
    }
    return any(
        item.get("category") == category and item.get("status") in desired_statuses
        for item in target.get("agent_actions", [])
    )


def _has_completed_action(target: dict[str, Any], category: str) -> bool:
    return _has_action_in_state(target, category, {"completed", "informational"})


def _web_base_url(ip_address: str, service: dict[str, Any]) -> str:
    port = int(service.get("port") or 0)
    service_name = (service.get("service") or "").lower()
    tunnel = (service.get("tunnel") or "").lower()
    scheme = "https" if service_name == "https" or tunnel == "ssl" or port in {443, 8443} else "http"
    if port in {80, 443}:
        return f"{scheme}://{ip_address}"
    return f"{scheme}://{ip_address}:{port}"


def _web_surface_token(service: dict[str, Any]) -> str:
    port = int(service.get("port") or 0)
    service_name = re.sub(r"[^a-z0-9]+", "-", (service.get("service") or "web").lower()).strip("-") or "web"
    return f"{service_name}-{port}"


def _preferred_web_wordlist() -> str:
    repo_wordlist = Path(__file__).resolve().parents[2] / "wordlists" / "common-web.txt"
    candidates = [
        str(repo_wordlist),
        "/opt/homebrew/share/seclists/Discovery/Web-Content/common.txt",
        "/opt/homebrew/share/dirb/wordlists/common.txt",
        "/usr/share/seclists/Discovery/Web-Content/common.txt",
        "/usr/share/seclists/Discovery/Web-Content/raft-small-words.txt",
        "/usr/share/wordlists/dirb/common.txt",
    ]
    for candidate in candidates:
        if Path(candidate).exists():
            return candidate
    return candidates[0]


def _infer_surface_token_from_command(command: str) -> str:
    port_match = re.search(r":(\d+)", command)
    if not port_match:
        port_match = re.search(r"-p\s+(\d+)", command)
    port = int(port_match.group(1)) if port_match else 80
    return f"http-{port}"


def _migrate_action_metadata(target: dict[str, Any]) -> bool:
    changed = False
    legacy_http_categories = {
        "http_fingerprint": ("web-fingerprint", 20, "Validate the web surface before using brute-force tooling."),
        "http_metadata": ("web-fingerprint", 21, "Look for quiet content clues before escalating to broader discovery."),
        "http_nse": ("web-fingerprint", 22, "Cross-check the surface with structured service data."),
        "http_twiki": ("targeted-web-enum", 24, "Follow the strongest content lead first."),
        "http_metasploitable_paths": ("targeted-web-enum", 25, "Use known training-target paths before blind fuzzing."),
    }
    operator_categories = {
        "operator_page_source": ("web-fingerprint", 18, "Capture the rendered source before making assumptions about the app."),
        "operator_page_source_note": ("web-fingerprint", 18, "Tie source analysis to a confirmed web surface."),
        "operator_sqlmap": ("focused-exploitation", 70, "Move into exploit validation only after the operator explicitly asks for it."),
        "operator_sqlmap_note": ("focused-exploitation", 70, "Do not launch SQL testing without a real web target."),
    }
    playbook_exact_categories = {
        "smb_enum": ("service-auth", 32, "Check for guest access before trying credentials."),
        "dns_axfr": ("service-enum", 18, "Use exposed infrastructure services to pivot into naming and trust data."),
        "full_tcp_recon": ("service-expansion", 12, "Confirm the full attack surface before committing to one path."),
    }

    for action in target.get("agent_actions", []):
        category = action.get("category") or ""
        if category in legacy_http_categories:
            stage, priority, mindset = legacy_http_categories[category]
            action["category"] = f"{category}_{_infer_surface_token_from_command(action.get('command', ''))}"
            if action.get("stage") in {None, "general"}:
                action["stage"] = stage
            if action.get("priority") in {None, 50}:
                action["priority"] = priority
            if not action.get("mindset"):
                action["mindset"] = mindset
            if action.get("source") in {None, "playbook"}:
                action["source"] = "playbook"
            changed = True
            continue
        if category in operator_categories:
            stage, priority, mindset = operator_categories[category]
            if action.get("stage") in {None, "general"}:
                action["stage"] = stage
                changed = True
            if action.get("priority") in {None, 50}:
                action["priority"] = priority
                changed = True
            if not action.get("mindset"):
                action["mindset"] = mindset
                changed = True
            if action.get("source") in {None, "playbook"}:
                action["source"] = "operator_prompt"
                changed = True
            continue
        if category in playbook_exact_categories:
            stage, priority, mindset = playbook_exact_categories[category]
            if action.get("stage") in {None, "general"}:
                action["stage"] = stage
                changed = True
            if action.get("priority") in {None, 50}:
                action["priority"] = priority
                changed = True
            if not action.get("mindset"):
                action["mindset"] = mindset
                changed = True
    return changed


def _directory_discovery_command(base_url: str) -> tuple[str, str]:
    wordlist = shlex.quote(_preferred_web_wordlist())
    safe_url = shlex.quote(f"{base_url.rstrip('/')}/FUZZ")
    if _tool_available("ffuf"):
        return (
            f"ffuf -w {wordlist} -u {safe_url} -mc all -fc 404 -t 30 -s",
            "ffuf",
        )
    if _tool_available("gobuster"):
        return (
            f"gobuster dir -q -u {shlex.quote(base_url)} -w {wordlist} -k",
            "gobuster",
        )
    if _tool_available("dirb"):
        return (
            f"dirb {shlex.quote(base_url)} {wordlist} -S",
            "dirb",
        )
    return (
        f"ffuf -w {wordlist} -u {safe_url} -mc all -fc 404 -t 30 -s",
        "ffuf",
    )


def _service_playbook_actions(target: dict[str, Any]) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    ip_address = target["ip_address"]
    for service in target.get("services", []):
        port = int(service.get("port") or 0)
        service_name = str(service.get("service") or "").lower()
        tunnel = str(service.get("tunnel") or "").lower()
        is_web = service_name in {"http", "https", "http-proxy"} or tunnel == "ssl" or port in {80, 443, 8000, 8080, 8443}
        if is_web:
            base_url = _web_base_url(ip_address, service)
            surface_token = _web_surface_token(service)
            if _tool_available("whatweb"):
                actions.append(
                    {
                        "label": f"Fingerprint web stack on {port}",
                        "risk": "safe",
                        "approval_required": True,
                        "reason": "Technology fingerprinting helps pick quieter next web checks before escalating further.",
                        "command": f"whatweb -a 2 {shlex.quote(base_url)}",
                        "parser": "generic_text",
                        "category": f"whatweb_{surface_token}",
                        "stage": "web-fingerprint",
                        "priority": 23,
                        "mindset": "Collect stack clues before launching broader web tooling.",
                        "source": "service_playbook",
                        "requires": ["web_surface"],
                        "produces": ["web_surface"],
                        "confidence": "observed",
                        "noise_level": "low",
                        "campaign": "web-enum",
                    }
                )
            if _tool_available("nikto"):
                actions.append(
                    {
                        "label": f"Run Nikto quick check on {port}",
                        "risk": "medium",
                        "approval_required": True,
                        "reason": "A single Nikto pass can surface low-hanging misconfigurations and known paths.",
                        "command": f"nikto -host {shlex.quote(base_url)} -maxtime 3m",
                        "parser": "generic_text",
                        "category": f"nikto_{surface_token}",
                        "stage": "targeted-web-enum",
                        "priority": 35,
                        "mindset": "Escalate from fingerprinting to bounded web checks.",
                        "source": "service_playbook",
                        "requires": ["web_surface"],
                        "produces": ["web_surface"],
                        "confidence": "candidate",
                        "noise_level": "medium",
                        "campaign": "web-enum",
                    }
                )
            if _tool_available("feroxbuster"):
                actions.append(
                    {
                        "label": f"Run recursive content discovery on {port}",
                        "risk": "medium",
                        "approval_required": True,
                        "reason": "Feroxbuster is a strong fallback when ffuf is absent or a deeper sweep is justified.",
                        "command": f"feroxbuster -u {shlex.quote(base_url)} -w {shlex.quote(_preferred_web_wordlist())} -q -k --dont-filter",
                        "parser": "generic_text",
                        "category": f"ferox_{surface_token}",
                        "stage": "content-discovery",
                        "priority": 37,
                        "mindset": "Broaden web coverage only after quieter checks have run.",
                        "source": "service_playbook",
                        "requires": ["web_surface"],
                        "produces": ["web_surface"],
                        "confidence": "candidate",
                        "noise_level": "medium",
                        "campaign": "web-enum",
                    }
                )
            if _tool_available("ffuf"):
                host_header = shlex.quote(f"Host: FUZZ.{ip_address}")
                actions.append(
                    {
                        "label": f"Run vhost discovery on {port}",
                        "risk": "medium",
                        "approval_required": True,
                        "reason": "Vhost enumeration is high-value on HTB when a web surface is present but content is sparse.",
                        "command": f"ffuf -w {shlex.quote(_preferred_web_wordlist())} -u {shlex.quote(base_url)} -H {host_header} -fs 0 -t 30 -s",
                        "parser": "generic_text",
                        "category": f"vhost_{surface_token}",
                        "stage": "content-discovery",
                        "priority": 38,
                        "mindset": "Look for alternate host routing before brute forcing parameters.",
                        "source": "service_playbook",
                        "requires": ["web_surface"],
                        "produces": ["web_surface"],
                        "confidence": "candidate",
                        "noise_level": "medium",
                        "campaign": "web-enum",
                    }
                )
        if port in {139, 445}:
            if _tool_available("smbmap"):
                actions.append(
                    {
                        "label": "Map SMB shares and permissions",
                        "risk": "safe",
                        "approval_required": True,
                        "reason": "SMBMap adds permissions context beyond a basic anonymous listing.",
                        "command": f"smbmap -H {ip_address}",
                        "parser": "generic_text",
                        "category": "smbmap_enum",
                        "stage": "service-auth",
                        "priority": 33,
                        "mindset": "Confirm share access level before trying credentials.",
                        "source": "service_playbook",
                        "requires": ["smb"],
                        "produces": ["smb"],
                        "confidence": "candidate",
                        "noise_level": "low",
                        "campaign": "smb-enum",
                    }
                )
            if _tool_available("enum4linux-ng"):
                actions.append(
                    {
                        "label": "Run enum4linux-ng against SMB",
                        "risk": "medium",
                        "approval_required": True,
                        "reason": "enum4linux-ng can expose users, shares, and domain hints in one bounded pass.",
                        "command": f"enum4linux-ng -A {ip_address}",
                        "parser": "generic_text",
                        "category": "enum4linux_ng",
                        "stage": "service-enum",
                        "priority": 36,
                        "mindset": "Gather Windows context before committing to credential tests.",
                        "source": "service_playbook",
                        "requires": ["smb"],
                        "produces": ["credentials"],
                        "confidence": "candidate",
                        "noise_level": "medium",
                        "campaign": "smb-enum",
                    }
                )
        if port == 21 and _tool_available("ftp"):
            actions.append(
                {
                    "label": "Check anonymous FTP access",
                    "risk": "safe",
                    "approval_required": True,
                    "reason": "Anonymous FTP remains a high-signal low-noise HTB check.",
                    "command": f"bash -lc 'printf \"user anonymous anonymous\\nls\\nquit\\n\" | ftp -inv {ip_address}'",
                    "parser": "generic_text",
                    "category": "ftp_anonymous",
                    "stage": "service-auth",
                    "priority": 31,
                    "mindset": "Probe anonymous access before switching to credential-driven FTP checks.",
                    "source": "service_playbook",
                    "requires": ["ftp"],
                    "produces": ["credentials"],
                    "confidence": "candidate",
                    "noise_level": "low",
                    "campaign": "service-auth",
                }
            )
        if port == 161 and _tool_available("snmpwalk"):
            actions.append(
                {
                    "label": "Walk public SNMP data",
                    "risk": "safe",
                    "approval_required": True,
                    "reason": "SNMP public community checks often yield usernames, software, or routing clues.",
                    "command": f"snmpwalk -v2c -c public {ip_address} 1",
                    "parser": "generic_text",
                    "category": "snmp_public",
                    "stage": "service-enum",
                    "priority": 26,
                    "mindset": "Mine infrastructure metadata before taking noisier paths.",
                    "source": "service_playbook",
                    "requires": ["snmp"],
                    "produces": ["credentials"],
                    "confidence": "candidate",
                    "noise_level": "low",
                    "campaign": "service-enum",
                }
            )
        if port in {389, 636} and _tool_available("ldapsearch"):
            actions.append(
                {
                    "label": "Run anonymous LDAP rootDSE query",
                    "risk": "safe",
                    "approval_required": True,
                    "reason": "A rootDSE query can reveal naming context and AD structure before auth attempts.",
                    "command": f"ldapsearch -x -H ldap://{ip_address}:{port} -s base namingcontexts defaultnamingcontext",
                    "parser": "generic_text",
                    "category": "ldap_rootdse",
                    "stage": "service-enum",
                    "priority": 27,
                    "mindset": "Confirm directory naming and scope before credential workflows.",
                    "source": "service_playbook",
                    "requires": ["ldap"],
                    "produces": ["credentials"],
                    "confidence": "candidate",
                    "noise_level": "low",
                    "campaign": "ad-enum",
                }
            )
    return actions


def _credential_pivot_actions(target: dict[str, Any]) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    ip_address = target["ip_address"]
    for credential in target.get("credentials", []):
        if credential.get("status") == "validated":
            continue
        username = credential.get("username")
        password = credential.get("password")
        if not username or not password:
            continue
        if any(int(service.get("port") or 0) in {139, 445} for service in target.get("services", [])):
            if _tool_available("netexec"):
                actions.append(
                    {
                        "label": f"Validate SMB credential {username}",
                        "risk": "medium",
                        "approval_required": True,
                        "reason": "A harvested credential should be validated against SMB before broader exploitation.",
                        "command": f"netexec smb {ip_address} -u {shlex.quote(username)} -p {shlex.quote(password)}",
                        "parser": "credential_probe",
                        "category": f"cred_validate_smb_{username}",
                        "stage": "credential-validation",
                        "priority": 42,
                        "mindset": "Turn a candidate credential into a confirmed access path.",
                        "source": "credential_engine",
                        "requires": ["credentials", "smb"],
                        "produces": ["validated_credential", "session"],
                        "confidence": "candidate",
                        "noise_level": "medium",
                        "stop_on_success": True,
                        "campaign": "credential-validation",
                    }
                )
            elif _tool_available("crackmapexec"):
                actions.append(
                    {
                        "label": f"Validate SMB credential {username} with CrackMapExec",
                        "risk": "medium",
                        "approval_required": True,
                        "reason": "CrackMapExec is the available fallback for validating SMB credentials.",
                        "command": f"crackmapexec smb {ip_address} -u {shlex.quote(username)} -p {shlex.quote(password)}",
                        "parser": "credential_probe",
                        "category": f"cred_validate_cme_{username}",
                        "stage": "credential-validation",
                        "priority": 43,
                        "mindset": "Confirm credential validity before launching remote execution.",
                        "source": "credential_engine",
                        "requires": ["credentials", "smb"],
                        "produces": ["validated_credential", "session"],
                        "confidence": "candidate",
                        "noise_level": "medium",
                        "stop_on_success": True,
                        "campaign": "credential-validation",
                    }
                )
        if any(int(service.get("port") or 0) == 21 for service in target.get("services", [])):
            actions.append(
                {
                    "label": f"Validate FTP credential {username}",
                    "risk": "medium",
                    "approval_required": True,
                    "reason": "FTP is in scope and the credential has not been tested there yet.",
                    "command": f"bash -lc 'printf \"user {shlex.quote(username)} {shlex.quote(password)}\\nls\\nquit\\n\" | ftp -inv {ip_address}'",
                    "parser": "credential_probe",
                    "category": f"cred_validate_ftp_{username}",
                    "stage": "credential-validation",
                    "priority": 44,
                    "mindset": "Validate the credential against the quietest plausible service first.",
                    "source": "credential_engine",
                    "requires": ["credentials", "ftp"],
                    "produces": ["validated_credential"],
                    "confidence": "candidate",
                    "noise_level": "medium",
                    "stop_on_success": True,
                    "campaign": "credential-validation",
                }
            )
    return actions


def _post_access_actions(target: dict[str, Any]) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    if not target.get("sessions"):
        return actions
    actions.append(
        {
            "label": "Collect user, groups, and hostname from the current session",
            "risk": "safe",
            "approval_required": True,
            "reason": "A foothold exists, so baseline identity and environment collection is the next step.",
            "command": "whoami && id && hostname",
            "parser": "session_probe",
            "category": "post_access_identity",
            "stage": "post-access",
            "priority": 48,
            "mindset": "Stabilize the foothold before privilege escalation.",
            "source": "objective_engine",
            "requires": ["session"],
            "produces": ["session"],
            "confidence": "observed",
            "noise_level": "low",
            "campaign": "post-access",
        }
    )
    actions.append(
        {
            "label": "Run quick privilege escalation triage",
            "risk": "medium",
            "approval_required": True,
            "reason": "The foothold should immediately be checked for obvious privesc paths.",
            "command": "sudo -n -l || true; getcap -r / 2>/dev/null | head -50; find / -perm -4000 -type f 2>/dev/null | head -50",
            "parser": "privesc_probe",
            "category": "post_access_privesc",
            "stage": "privesc",
            "priority": 52,
            "mindset": "Convert foothold context into the first privilege-escalation hypothesis.",
            "source": "objective_engine",
            "requires": ["session"],
            "produces": ["privesc_signal"],
            "confidence": "candidate",
            "noise_level": "medium",
            "stop_on_success": True,
            "campaign": "post-access",
        }
    )
    return actions


def _attack_engine_action_templates(target: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        *_service_playbook_actions(target),
        *_credential_pivot_actions(target),
        *_post_access_actions(target),
    ]


def _execution_runtime_key(execution_kind: str, execution_id: str) -> str:
    return f"{execution_kind}:{execution_id}"


def _read_process_stream(stream, source: str, sink: queue.Queue[tuple[str, str]]) -> None:
    try:
        for chunk in iter(stream.readline, ""):
            if not chunk:
                break
            sink.put((source, chunk))
    finally:
        stream.close()


def _append_tail(existing: str, chunk: str) -> str:
    combined = f"{existing}{chunk}"
    if len(combined) <= LIVE_OUTPUT_TAIL_LIMIT:
        return combined
    return combined[-LIVE_OUTPUT_TAIL_LIMIT:]


def _update_execution_record(target: dict[str, Any], execution_kind: str, execution_id: str, mutator) -> bool:
    collection_name = "jobs" if execution_kind == "job" else "agent_actions"
    for item in target.get(collection_name, []):
        if item["id"] == execution_id:
            mutator(item)
            return True
    return False


def _update_execution_state(target_id: str, execution_kind: str, execution_id: str, mutator) -> dict[str, Any]:
    def apply(target: dict[str, Any]) -> None:
        if not _update_execution_record(target, execution_kind, execution_id, mutator):
            raise HTTPException(status_code=404, detail=f"{execution_kind.title()} not found")

    return _with_target_lock(target_id, apply)


def _set_execution_runtime(
    execution_kind: str,
    execution_id: str,
    **fields: Any,
) -> dict[str, Any]:
    key = _execution_runtime_key(execution_kind, execution_id)
    with RUNTIME_LOCK:
        runtime = EXECUTION_RUNTIME.setdefault(
            key,
            {
                "execution_kind": execution_kind,
                "execution_id": execution_id,
                "tail": "",
                "last_output_at": None,
                "output_bytes": 0,
                "events": [],
                "stop_requested_at": None,
                "termination_reason": None,
                "pid": None,
                "finished_at": None,
                "return_code": None,
            },
        )
        runtime.update(fields)
        if "event" in fields and fields["event"]:
            runtime["events"] = [*runtime.get("events", []), fields["event"]][-LIVE_EVENT_LIMIT:]
        return dict(runtime)


def _get_execution_runtime(execution_kind: str, execution_id: str) -> dict[str, Any] | None:
    key = _execution_runtime_key(execution_kind, execution_id)
    with RUNTIME_LOCK:
        runtime = EXECUTION_RUNTIME.get(key)
        return dict(runtime) if runtime else None


def _record_execution_output(
    target_id: str,
    execution_kind: str,
    execution_id: str,
    chunk: str,
    output_path: Path,
) -> None:
    timestamp = _now()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("a", encoding="utf-8", errors="replace") as handle:
        handle.write(chunk)
    runtime = _get_execution_runtime(execution_kind, execution_id) or {}
    tail = _append_tail(runtime.get("tail", ""), chunk)
    output_bytes = int(runtime.get("output_bytes", 0)) + len(chunk.encode("utf-8", errors="replace"))
    _set_execution_runtime(
        execution_kind,
        execution_id,
        tail=tail,
        last_output_at=timestamp,
        output_bytes=output_bytes,
    )

    def mark_output(item: dict[str, Any]) -> None:
        item["output_path"] = str(output_path)
        item["live_output_tail"] = tail
        item["last_output_at"] = timestamp
        item["output_bytes"] = output_bytes
        item["updated_at"] = timestamp

    _update_execution_state(target_id, execution_kind, execution_id, mark_output)


def _stream_process_output(
    target_id: str,
    execution_kind: str,
    execution_id: str,
    process: subprocess.Popen[str],
    output_path: Path,
    timeout_seconds: int,
) -> None:
    started = time.monotonic()
    sink: queue.Queue[tuple[str, str]] = queue.Queue()
    threads = [
        threading.Thread(target=_read_process_stream, args=(process.stdout, "stdout", sink), daemon=True),
        threading.Thread(target=_read_process_stream, args=(process.stderr, "stderr", sink), daemon=True),
    ]
    for thread in threads:
        thread.start()

    while True:
        emitted = False
        while True:
            try:
                source, chunk = sink.get_nowait()
            except queue.Empty:
                break
            emitted = True
            formatted = chunk if source == "stdout" else f"[stderr] {chunk}"
            _record_execution_output(target_id, execution_kind, execution_id, formatted, output_path)
        if process.poll() is not None:
            break
        if time.monotonic() - started > timeout_seconds:
            process.terminate()
            try:
                process.wait(timeout=PROCESS_STOP_WAIT_SECONDS)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=PROCESS_STOP_WAIT_SECONDS)
            raise subprocess.TimeoutExpired(process.args, timeout_seconds)
        if not emitted:
            time.sleep(0.15)

    for thread in threads:
        thread.join(timeout=0.5)
    while True:
        try:
            source, chunk = sink.get_nowait()
        except queue.Empty:
            break
        formatted = chunk if source == "stdout" else f"[stderr] {chunk}"
        _record_execution_output(target_id, execution_kind, execution_id, formatted, output_path)


def _request_execution_stop(execution_kind: str, execution_id: str) -> dict[str, Any]:
    runtime = _get_execution_runtime(execution_kind, execution_id)
    if not runtime or not runtime.get("process"):
        raise HTTPException(status_code=409, detail=f"{execution_kind.title()} is not actively running")

    process = runtime["process"]
    timestamp = _now()
    _set_execution_runtime(
        execution_kind,
        execution_id,
        stop_requested_at=timestamp,
        termination_reason="operator_stop_requested",
    )
    if process.poll() is not None:
        return _get_execution_runtime(execution_kind, execution_id) or runtime

    process.terminate()
    try:
        process.wait(timeout=PROCESS_STOP_WAIT_SECONDS)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=PROCESS_STOP_WAIT_SECONDS)
    return _get_execution_runtime(execution_kind, execution_id) or runtime


def _resize_pty(fd: int, cols: int, rows: int) -> None:
    packed = rows.to_bytes(2, "little") + cols.to_bytes(2, "little") + b"\x00\x00\x00\x00"
    fcntl.ioctl(fd, termios.TIOCSWINSZ, packed)


def _session_host_for_target(target: dict[str, Any], requested_host: str | None) -> str:
    host = (requested_host or target["ip_address"]).strip()
    allowed_hosts = {target["ip_address"], *(target.get("hostnames") or [])}
    if host not in allowed_hosts:
        raise HTTPException(status_code=400, detail="Shell host must match the selected target IP or known hostname")
    return host


def _shell_command_for_session(target: dict[str, Any], payload: ShellSessionInput) -> tuple[list[str], str, list[str]]:
    host = _session_host_for_target(target, payload.host)
    warnings: list[str] = []
    if payload.protocol == "ssh":
        destination = f"{payload.username}@{host}" if payload.username else host
        ssh_args = [
            "ssh",
            "-tt",
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "UserKnownHostsFile=/dev/null",
            "-o",
            "ConnectTimeout=10",
            "-p",
            str(payload.port),
            destination,
        ]
        if payload.password and shutil.which("sshpass"):
            return ["sshpass", "-p", payload.password, *ssh_args], f"ssh -tt -p {payload.port} {destination}", warnings
        if payload.password:
            warnings.append("sshpass is not installed; type the password manually if SSH prompts for it.")
        return ssh_args, f"ssh -tt -p {payload.port} {destination}", warnings
    if payload.protocol == "telnet":
        binary = "telnet"
        if not shutil.which(binary):
            warnings.append("telnet is not installed on this host.")
        return [binary, host, str(payload.port)], f"telnet {host} {payload.port}", warnings

    binary = "nc" if shutil.which("nc") else "ncat"
    if not shutil.which(binary):
        warnings.append("Neither nc nor ncat is installed on this host.")
    return [binary, host, str(payload.port)], f"{binary} {host} {payload.port}", warnings


def _create_shell_token(target_id: str, payload: ShellSessionInput) -> dict[str, Any]:
    target = _load_target(target_id)
    command, command_display, warnings = _shell_command_for_session(target, payload)
    token = _new_id("shelltok")
    session = {
        "token": token,
        "target_id": target_id,
        "protocol": payload.protocol,
        "host": _session_host_for_target(target, payload.host),
        "port": payload.port,
        "username": payload.username or "",
        "label": payload.label or command_display,
        "command": command,
        "command_display": command_display,
        "warnings": warnings,
        "cols": payload.cols,
        "rows": payload.rows,
        "created_at": time.monotonic(),
        "expires_at": time.monotonic() + SHELL_TOKEN_TTL_SECONDS,
    }
    with RUNTIME_LOCK:
        now = time.monotonic()
        expired = [key for key, item in SHELL_SESSION_TOKENS.items() if item.get("expires_at", 0) < now]
        for key in expired:
            SHELL_SESSION_TOKENS.pop(key, None)
        SHELL_SESSION_TOKENS[token] = session
    _log_activity(
        target_id,
        "shell_session_prepared",
        "Prepared interactive shell session.",
        {"protocol": payload.protocol, "host": session["host"], "port": payload.port, "username": payload.username or None},
    )
    return session


def _consume_shell_token(token: str) -> dict[str, Any] | None:
    with RUNTIME_LOCK:
        session = SHELL_SESSION_TOKENS.pop(token, None)
    if not session or session.get("expires_at", 0) < time.monotonic():
        return None
    return session


def _terminate_shell_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        process.wait(timeout=PROCESS_STOP_WAIT_SECONDS)
    except Exception:
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        except Exception:
            process.kill()


def _binary_for_command(command: str) -> str:
    return shlex.split(command)[0]


def _action_catalog(target: dict[str, Any], services: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ip_address = target["ip_address"]
    actions: list[dict[str, Any]] = []
    knowledge_text = _target_knowledge_text(target)
    has_metasploitable_hint = "metasploitable2" in knowledge_text or "metasploitable" in knowledge_text
    has_twiki_hint = "twiki" in knowledge_text

    if not services:
        actions.append(
            {
                "label": "Widen the port sweep",
                "risk": "safe",
                "approval_required": True,
                "reason": "The first scan did not find open TCP services. A full safe sweep is the next evidence-backed move.",
                "command": f"{NMAP_BIN} -Pn -p- --min-rate 2000 -oN /dev/stdout {ip_address}",
                "parser": "nmap_text",
                "category": "port_sweep",
                "stage": "service-expansion",
                "priority": 10,
                "mindset": "Expand coverage before choosing protocol-specific tooling.",
                "source": "playbook",
            }
        )
        return actions

    seen_smb = False
    seen_dns = False
    if has_metasploitable_hint and len(services) <= 3:
        actions.append(
            {
                "label": "Run a full TCP service sweep",
                "risk": "safe",
                "approval_required": True,
                "reason": "Metasploitable-style hosts normally expose more services than the current top-ports scan captured, so a full TCP pass should come before deeper exploitation.",
                "command": f"{NMAP_BIN} -Pn -p- -sV --version-light -oN /dev/stdout {ip_address}",
                "parser": "nmap_text",
                "category": "full_tcp_recon",
                "stage": "service-expansion",
                "priority": 12,
                "mindset": "Confirm the full attack surface before committing to one path.",
                "source": "playbook",
            }
        )
    for service in services:
        service_name = (service["service"] or "").lower()
        port = int(service["port"])
        tunnel = (service.get("tunnel") or "").lower()
        is_web = service_name in {"http", "http-proxy", "https"} or tunnel == "ssl" or port in {80, 443, 8080, 8000, 8443}
        if is_web:
            base_url = _web_base_url(ip_address, service)
            surface_token = _web_surface_token(service)
            actions.extend(
                [
                    {
                        "label": f"Fetch headers and landing page on {port}",
                        "risk": "safe",
                        "approval_required": True,
                        "reason": "A small HTTP fetch often reveals server family, titles, redirects, and default credentials hints.",
                        "command": f"curl -iskL --max-time 15 {base_url}",
                        "parser": "http_response",
                        "category": f"http_fingerprint_{surface_token}",
                        "stage": "web-fingerprint",
                        "priority": 20,
                        "mindset": "Validate the web surface before using brute-force tooling.",
                        "source": "playbook",
                    },
                    {
                        "label": f"Check common HTTP metadata on {port}",
                        "risk": "safe",
                        "approval_required": True,
                        "reason": "robots.txt and readme files can reveal stack details without noisy fuzzing.",
                        "command": f"curl -skL --max-time 15 {base_url}/robots.txt && printf '\\n\\n---\\n\\n' && curl -skL --max-time 15 {base_url}/readme.txt",
                        "parser": "http_text_blobs",
                        "category": f"http_metadata_{surface_token}",
                        "stage": "web-fingerprint",
                        "priority": 21,
                        "mindset": "Look for quiet content clues before escalating to broader discovery.",
                        "source": "playbook",
                    },
                    {
                        "label": f"Run lightweight NSE web scripts on {port}",
                        "risk": "safe",
                        "approval_required": True,
                        "reason": "NSE scripts can capture title and headers in a structured way before broader enumeration.",
                        "command": f"{NMAP_BIN} -Pn -p {port} --script http-title,http-headers {ip_address}",
                        "parser": "nmap_text",
                        "category": f"http_nse_{surface_token}",
                        "stage": "web-fingerprint",
                        "priority": 22,
                        "mindset": "Cross-check the surface with structured service data.",
                        "source": "playbook",
                    },
                ]
            )
            if has_twiki_hint:
                actions.append(
                    {
                        "label": "Inspect the TWiki path directly",
                        "risk": "safe",
                        "approval_required": True,
                        "reason": "The prior HTTP response mentioned TWiki, so a targeted fetch is more useful than repeating the homepage request.",
                        "command": f"curl -skL --max-time 15 {base_url}/twiki/ && printf '\\n\\n---\\n\\n' && curl -skL --max-time 15 {base_url}/twiki/readme.txt",
                        "parser": "http_text_blobs",
                        "category": f"http_twiki_{surface_token}",
                        "stage": "targeted-web-enum",
                        "priority": 24,
                        "mindset": "Follow the strongest content lead first.",
                        "source": "playbook",
                    }
                )
            if has_metasploitable_hint:
                actions.append(
                    {
                        "label": "Probe known Metasploitable web paths",
                        "risk": "safe",
                        "approval_required": True,
                        "reason": "The HTTP title matches Metasploitable2, so targeted low-noise path checks are more useful than blind directory fuzzing.",
                        "command": (
                            f"curl -skL --max-time 15 {base_url}/twiki/ && printf '\\n\\n---\\n\\n' && "
                            f"curl -skL --max-time 15 {base_url}/dvwa/ && printf '\\n\\n---\\n\\n' && "
                            f"curl -skL --max-time 15 {base_url}/phpMyAdmin/"
                        ),
                        "parser": "http_text_blobs",
                        "category": f"http_metasploitable_paths_{surface_token}",
                        "stage": "targeted-web-enum",
                        "priority": 25,
                        "mindset": "Use known training-target paths before blind fuzzing.",
                        "source": "playbook",
                    }
                )
            if "tomcat" in (service.get("detail") or "").lower() or port in {8080, 8180, 8443}:
                actions.extend(
                    [
                        {
                            "label": f"Probe Tomcat manager on {port}",
                            "risk": "safe",
                            "approval_required": True,
                            "reason": "Tomcat manager and host-manager endpoints often signal whether default credential testing is worth attempting.",
                            "command": f"curl -iskL --max-time 15 {base_url}/manager/html && printf '\\n\\n---\\n\\n' && curl -iskL --max-time 15 {base_url}/host-manager/html",
                            "parser": "http_response",
                            "category": f"tomcat_manager_probe_{surface_token}",
                            "stage": "auth-scouting",
                            "priority": 28,
                            "mindset": "Validate admin surfaces before trying credentials.",
                            "source": "playbook",
                        },
                        {
                            "label": f"Test common Tomcat default credentials on {port}",
                            "risk": "medium",
                            "approval_required": True,
                            "reason": "The Tomcat service is exposed, so a short list of high-probability defaults is a justified HTB-style credential check.",
                            "command": (
                                f"bash -lc 'for cred in tomcat:tomcat admin:admin manager:manager root:root; do "
                                f"code=$(curl -sk -o /dev/null -w \"%{{http_code}}\" -u \"$cred\" {base_url}/manager/html); "
                                f"printf \"%s -> %s\\n\" \"$cred\" \"$code\"; done'"
                            ),
                            "parser": "generic_text",
                            "category": f"tomcat_default_creds_{surface_token}",
                            "stage": "default-creds",
                            "priority": 30,
                            "mindset": "Try only short, high-signal default credentials after confirming the admin surface.",
                            "source": "playbook",
                        },
                    ]
                )
            if has_metasploitable_hint or has_twiki_hint or _has_completed_action(target, f"http_metadata_{surface_token}"):
                direnum_command, direnum_tool = _directory_discovery_command(base_url)
                actions.append(
                    {
                        "label": f"Run focused content discovery on {port}",
                        "risk": "medium",
                        "approval_required": True,
                        "reason": "After the quiet web checks, a single directory-enumeration pass is the next HTB-style move to extend coverage.",
                        "command": direnum_command,
                        "parser": "generic_text",
                        "category": f"web_content_discovery_{surface_token}",
                        "stage": "content-discovery",
                        "priority": 34,
                        "mindset": "Escalate from targeted checks to controlled content discovery.",
                        "source": "playbook",
                        "preferred_tool": direnum_tool,
                    }
                )
        if port in {139, 445} and not seen_smb:
            actions.append(
                {
                    "label": "Check anonymous SMB access",
                    "risk": "safe",
                    "approval_required": True,
                    "reason": "Anonymous share listing is usually a low-risk first SMB check.",
                    "command": f"smbclient -N -L //{ip_address}",
                    "parser": "smbclient_listing",
                    "category": "smb_enum",
                    "stage": "service-auth",
                    "priority": 32,
                    "mindset": "Check for guest access before trying credentials.",
                    "source": "playbook",
                }
            )
            seen_smb = True
        if port == 53 and not seen_dns:
            actions.append(
                {
                    "label": "Attempt a DNS zone transfer",
                    "risk": "safe",
                    "approval_required": True,
                    "reason": "Zone transfer checks are compact and often decisive when TCP/53 is exposed.",
                    "command": f"dig axfr @{ip_address}",
                    "parser": "dns_axfr",
                    "category": "dns_axfr",
                    "stage": "service-enum",
                    "priority": 18,
                    "mindset": "Use exposed infrastructure services to pivot into naming and trust data.",
                    "source": "playbook",
                }
            )
            seen_dns = True
        if port == 22:
            actions.append(
                {
                    "label": "Preserve SSH as a post-discovery path",
                    "risk": "informational",
                    "approval_required": False,
                    "reason": "SSH is open, but the harness should wait for credentials or keys from other surfaces first.",
                    "command": "Hold off on auth attempts until the harness finds credentials, usernames, or keys.",
                    "parser": "note",
                    "category": "ssh_note",
                    "stage": "credential-staging",
                    "priority": 60,
                    "mindset": "Save SSH for when another surface yields credentials.",
                    "source": "playbook",
                }
            )
    return actions


def _build_recommendations_from_actions(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": item["id"],
            "label": item["label"],
            "risk": item["risk"],
            "why": item["reason"],
            "command": item["command"],
            "status": item["status"],
            "stage": item.get("stage"),
            "priority": item.get("priority"),
            "source": item.get("source"),
            "mindset": item.get("mindset"),
            "campaign": item.get("campaign"),
            "confidence": item.get("confidence"),
            "noise_level": item.get("noise_level"),
        }
        for item in [action for action in actions if action["status"] not in {"denied", "removed", "failed"}][:8]
    ]


def _default_recommendations(ip_address: str) -> list[dict[str, Any]]:
    return [
        {
            "id": _new_id("rec"),
            "label": "Run the baseline safe scan",
            "risk": "safe",
            "why": "Start with service discovery before choosing protocol-specific tooling.",
            "command": f"{NMAP_BIN} -Pn -T4 --top-ports 1000 -sV --version-light {ip_address}",
            "status": "informational",
            "stage": "initial-recon",
            "priority": 10,
            "source": "playbook",
            "mindset": "Build the first service map before selecting tools.",
        }
    ]


def _action_from_template(template: dict[str, Any]) -> dict[str, Any]:
    template = {
        "requires": [],
        "produces": [],
        "confidence": "candidate",
        "noise_level": "low",
        "stop_on_success": False,
        "campaign": "general",
        **template,
    }
    parser = template["parser"]
    binary = None if parser == "note" else _binary_for_command(template["command"])
    available = True if parser == "note" else _tool_available(binary)
    status = "informational" if not template["approval_required"] else ("pending_approval" if available else "blocked")
    return {
        "id": _new_id("act"),
        "label": template["label"],
        "risk": template["risk"],
        "reason": template["reason"],
        "command": template["command"],
        "parser": parser,
        "category": template["category"],
        "stage": template.get("stage", "general"),
        "priority": int(template.get("priority", 50)),
        "source": template.get("source", "playbook"),
        "mindset": template.get("mindset"),
        "requires": list(template.get("requires") or []),
        "produces": list(template.get("produces") or []),
        "confidence": template.get("confidence", "candidate"),
        "noise_level": template.get("noise_level", "low"),
        "stop_on_success": bool(template.get("stop_on_success", False)),
        "campaign": template.get("campaign", "general"),
        "status": status,
        "approval_required": template["approval_required"],
        "auto_approved": False,
        "tool_available": available,
        "binary": binary,
        "created_at": _now(),
        "updated_at": _now(),
        "approved_at": None,
        "denied_at": None,
        "started_at": None,
        "finished_at": None,
        "output_path": None,
        "summary": None,
        "parse_summary": None,
        "result_excerpt": None,
        "error": None,
        "decision_note": None,
        "pid": None,
        "output_bytes": 0,
        "last_output_at": None,
        "live_output_tail": "",
        "stop_requested_at": None,
        "termination_reason": None,
    }


def _append_action_templates(
    target: dict[str, Any],
    templates: list[dict[str, Any]],
    *,
    auto_approve_allowed: bool = True,
) -> list[dict[str, Any]]:
    existing_signatures = {
        _action_signature(item): item
        for item in target.get("agent_actions", [])
        if item.get("status") not in {"denied", "removed", "failed"}
    }
    failed_commands = {
        str(item.get("command") or "").strip()
        for item in target.get("agent_actions", [])
        if item.get("status") == "failed"
    }
    created: list[dict[str, Any]] = []
    for template in templates:
        allowed, _ = _action_policy_verdict(target, template)
        if template.get("source") != "operator_prompt" and not allowed:
            continue
        signature = f"{template['category']}::{template['command']}"
        if signature in existing_signatures or str(template["command"]).strip() in failed_commands:
            continue
        action = _action_from_template(template)
        target.setdefault("agent_actions", []).append(action)
        existing_signatures[signature] = action
        created.append(action)
    if auto_approve_allowed and created:
        _auto_approve_allowlisted_actions(target)
    if created:
        target["recommendations"] = _build_recommendations_from_actions(target["agent_actions"]) or _default_recommendations(target["ip_address"])
    return created


def _new_target(ip_address: str, label: str | None) -> dict[str, Any]:
    created_at = _now()
    target_id = _new_id("target")
    display_name = label.strip() if label else f"HTB {ip_address}"
    target = {
        "schema_version": STATE_SCHEMA_VERSION,
        "id": target_id,
        "ip_address": ip_address,
        "label": label.strip() if label else None,
        "display_name": display_name,
        "status": "ready",
        "phase": "awaiting_enumeration",
        "created_at": created_at,
        "updated_at": created_at,
        "services": [],
        "hostnames": [],
        "findings": [],
        "agent_actions": [],
        "observations": [],
        "credentials": [],
        "sessions": [],
        "artifacts": [],
        "paths": [],
        "objectives": _default_objectives(),
        "hosts": _default_host_records(ip_address),
        "web_surfaces": [],
        "attack_graph": _default_attack_graph(ip_address),
        "best_path": None,
        "decision_journal": [],
        "autonomy": _default_autonomy_state(),
        "context_blocks": [],
        "conversation": [],
        "llm_calls": [],
        "llm_agent": _default_llm_agent_state(),
        "recommendations": _default_recommendations(ip_address),
        "jobs": [],
        "timeline": [
            _timeline_event(
                "target_created",
                f"Target {ip_address} added to mission control.",
                {"ip_address": ip_address, "label": label},
            )
        ],
        "latest_summary": "Target created. Enumeration has not started yet.",
    }
    _save_target(target)
    _log_activity(target_id, "target_created", "Created target record.", {"ip_address": ip_address, "label": label})
    return target


def _build_nmap_command(target: dict[str, Any], job_id: str) -> tuple[list[str], Path, Path]:
    scans_dir = _artifacts_dir(target["id"], "scans")
    scans_dir.mkdir(parents=True, exist_ok=True)
    scan_prefix = scans_dir / f"{job_id}_initial"
    xml_path = scan_prefix.with_suffix(".xml")
    text_path = scan_prefix.with_suffix(".nmap")
    command = [
        NMAP_BIN,
        "-Pn",
        "-T4",
        "--top-ports",
        "1000",
        "-sV",
        "--version-light",
        "-oX",
        str(xml_path),
        "-oN",
        str(text_path),
        target["ip_address"],
    ]
    return command, xml_path, text_path


def _parse_nmap_xml(xml_path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    if not xml_path.exists():
        return [], []
    tree = ET.parse(xml_path)
    root = tree.getroot()
    services: list[dict[str, Any]] = []
    hostnames: list[str] = []
    for hostname in root.findall(".//hostname"):
        name = hostname.attrib.get("name")
        if name and name not in hostnames:
            hostnames.append(name)
    for port in root.findall(".//port"):
        state = port.find("state")
        if state is None or state.attrib.get("state") != "open":
            continue
        service = port.find("service")
        service_name = service.attrib.get("name", "unknown") if service is not None else "unknown"
        product = service.attrib.get("product", "") if service is not None else ""
        version = service.attrib.get("version", "") if service is not None else ""
        extrainfo = service.attrib.get("extrainfo", "") if service is not None else ""
        tunnel = service.attrib.get("tunnel", "") if service is not None else ""
        detail = " ".join(part for part in [product, version, extrainfo] if part).strip()
        services.append(
            {
                "port": int(port.attrib["portid"]),
                "protocol": port.attrib.get("protocol", "tcp"),
                "service": service_name,
                "tunnel": tunnel,
                "detail": detail,
            }
        )
    services.sort(key=lambda item: (item["protocol"], item["port"]))
    return services, hostnames


def _service_severity(service_name: str, port: int) -> str:
    risky = {"microsoft-ds", "smb", "ldap", "msrpc", "mysql", "postgresql", "redis", "winrm"}
    if port in {139, 445, 389, 5985, 5986} or service_name.lower() in risky:
        return "medium"
    if service_name.lower() in {"http", "https", "ssh", "ftp"}:
        return "low"
    return "info"


def _build_findings(services: list[dict[str, Any]], observations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for service in services:
        findings.append(
            {
                "id": _new_id("finding"),
                "title": f"Open {service['service']} service on {service['port']}/{service['protocol']}",
                "severity": _service_severity(service["service"], service["port"]),
                "evidence": f"Observed in enumeration: {service['service']} on port {service['port']} {service['detail']}".strip(),
                "confidence": "observed",
                "port": service["port"],
            }
        )
    for observation in observations[-8:]:
        findings.append(
            {
                "id": _new_id("finding"),
                "title": observation["title"],
                "severity": observation.get("severity", "info"),
                "evidence": observation.get("summary", ""),
                "confidence": observation.get("confidence", "observed"),
                "port": observation.get("port"),
            }
        )
    if not findings:
        findings.append(
            {
                "id": _new_id("finding"),
                "title": "No open TCP services identified in the baseline scan",
                "severity": "info",
                "evidence": "The default initial scan did not report open TCP services.",
                "confidence": "observed",
                "port": None,
            }
        )
    return findings


def _compose_summary(target: dict[str, Any]) -> str:
    services = target.get("services", [])
    completed_actions = [item for item in target.get("agent_actions", []) if item["status"] == "completed"]
    pending_actions = _pending_approval_actions(target)
    observations = target.get("observations", [])
    credentials = target.get("credentials", [])
    sessions = target.get("sessions", [])
    if not services:
        return "Baseline enumeration finished without open TCP services. Review the proposed wider scan."
    service_list = ", ".join(f"{item['port']}/{item['protocol']} {item['service']}" for item in services[:6])
    summary = f"Objective {_current_objective_phase(target)}. Baseline enumeration found {len(services)} open services: {service_list}."
    if observations:
        summary += f" Latest observation: {observations[-1]['summary']}"
    if credentials:
        summary += f" {len(credentials)} credential candidate(s) are now structured in state."
    if sessions:
        summary += f" {len(sessions)} session foothold(s) are recorded."
    if pending_actions:
        summary += f" {len(pending_actions)} action(s) are waiting for approval."
    elif completed_actions:
        summary += f" {len(completed_actions)} approved action(s) have completed."
    return summary


def _action_signature(action: dict[str, Any]) -> str:
    return f"{action['category']}::{action['command']}"


def _pending_approval_actions(target: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        item
        for item in target.get("agent_actions", [])
        if item.get("status") in {"pending_approval", "blocked"}
    ]


def _resting_target_phase(target: dict[str, Any]) -> str:
    if _pending_approval_actions(target):
        return "awaiting_approval"
    if target.get("services"):
        return "enumerated"
    if target.get("phase") == "enumeration_failed":
        return "enumeration_failed"
    return "awaiting_enumeration"


def _refresh_agent_actions(target: dict[str, Any]) -> None:
    completed_signatures = {
        _action_signature(item)
        for item in target.get("agent_actions", [])
        if item["status"] in {"completed", "informational"}
    }
    pending_signatures: set[str] = set()
    filtered_actions: list[dict[str, Any]] = []
    for item in target.get("agent_actions", []):
        signature = _action_signature(item)
        if item["status"] in {"pending_approval", "blocked"} and signature in completed_signatures:
            continue
        if item["status"] in {"pending_approval", "blocked"}:
            if signature in pending_signatures:
                continue
            pending_signatures.add(signature)
        filtered_actions.append(item)
    target["agent_actions"] = filtered_actions

    desired = [
        *_action_catalog(target, target.get("services", [])),
        *_attack_engine_action_templates(target),
    ]
    existing = {
        _action_signature(item): item
        for item in target.get("agent_actions", [])
        if item["status"] not in {"denied"}
    }
    for template in desired:
        signature = f"{template['category']}::{template['command']}"
        if signature in existing:
            continue
        _append_action_templates(target, [template])

    _auto_approve_allowlisted_actions(target)
    target["recommendations"] = _build_recommendations_from_actions(target["agent_actions"]) or _default_recommendations(target["ip_address"])


def _job_is_active(target: dict[str, Any]) -> bool:
    return any(job["status"] in {"queued", "running", "stopping"} for job in target.get("jobs", []))


def _action_is_active(target: dict[str, Any]) -> bool:
    return any(item["status"] in {"approved", "running", "stopping"} for item in target.get("agent_actions", []))


def _dispatch_next_approved_action(target_id: str) -> bool:
    with STATE_LOCK:
        target = _load_target(target_id)
        if any(item["status"] == "running" for item in target.get("agent_actions", [])):
            return False
        next_action = next((item for item in target.get("agent_actions", []) if item.get("status") == "approved"), None)
        if next_action is None:
            return False
    threading.Thread(target=_run_agent_action, args=(target_id, next_action["id"]), daemon=True).start()
    return True


def _delete_target(target_id: str) -> None:
    with STATE_LOCK:
        target = _load_target(target_id)
        if _job_is_active(target) or _action_is_active(target):
            raise HTTPException(status_code=409, detail="Target has a running job or action")
        shutil.rmtree(_target_dir(target_id), ignore_errors=True)


def _remove_action(target_id: str, action_id: str, note: str | None) -> dict[str, Any]:
    def remove_action(target: dict[str, Any]) -> None:
        actions = target.get("agent_actions", [])
        action = next((item for item in actions if item["id"] == action_id), None)
        if action is None:
            raise HTTPException(status_code=404, detail="Action not found")
        if action.get("status") == "running":
            raise HTTPException(status_code=409, detail="Cannot remove a running action")
        output_path = action.get("output_path")
        if output_path:
            Path(output_path).unlink(missing_ok=True)
        action["status"] = "removed"
        action["updated_at"] = _now()
        action["finished_at"] = action.get("finished_at") or _now()
        action["decision_note"] = note
        action["error"] = None
        action["output_path"] = None
        target["recommendations"] = _build_recommendations_from_actions(target["agent_actions"]) or _default_recommendations(target["ip_address"])
        target["latest_summary"] = _compose_summary(target)
        target["timeline"].append(
            _timeline_event("action_removed", "User removed an action from the approval queue.", {"action_id": action_id, "note": note})
        )

    saved = _with_target_lock(target_id, remove_action)
    _log_activity(target_id, "action_removed", "User removed action.", {"action_id": action_id, "note": note})
    return saved


def _start_enumeration(target_id: str) -> dict[str, Any]:
    with STATE_LOCK:
        target = _load_target(target_id)
        if _job_is_active(target):
            active_job = next(job for job in reversed(target["jobs"]) if job["status"] in {"queued", "running"})
            return active_job

        job_id = _new_id("job")
        command, _, text_path = _build_nmap_command(target, job_id)
        job = {
            "id": job_id,
            "kind": "enumeration",
            "label": "Initial baseline enumeration",
            "status": "queued",
            "command": " ".join(shlex.quote(part) for part in command),
            "created_at": _now(),
            "updated_at": _now(),
            "started_at": None,
            "finished_at": None,
            "output_path": str(text_path),
            "error": None,
            "return_code": None,
            "summary": None,
            "pid": None,
            "output_bytes": 0,
            "last_output_at": None,
            "live_output_tail": "",
            "stop_requested_at": None,
            "termination_reason": None,
        }
        target["jobs"].append(job)
        target["status"] = "enumerating"
        target["phase"] = "initial_enumeration"
        target["latest_summary"] = "Baseline enumeration queued. Waiting for scan results."
        target["timeline"].append(
            _timeline_event("job_queued", "Queued the baseline enumeration scan.", {"job_id": job_id})
        )
        _save_target(target)

    _log_activity(target_id, "job_queued", "Queued baseline enumeration.", {"job_id": job_id})
    EXECUTOR.submit(_run_enumeration_job, target_id, job_id)
    return job


def _run_enumeration_job(target_id: str, job_id: str) -> None:
    def mark_running(target: dict[str, Any]) -> None:
        for job in target["jobs"]:
            if job["id"] == job_id:
                if job["status"] == "stopped":
                    return
                job["status"] = "running"
                job["started_at"] = _now()
                job["updated_at"] = _now()
                break
        target["latest_summary"] = "Baseline enumeration is running."
        target["timeline"].append(
            _timeline_event("job_started", "Initial enumeration scan is running.", {"job_id": job_id})
        )

    target_after_start = _with_target_lock(target_id, mark_running)
    started_job = next((item for item in target_after_start["jobs"] if item["id"] == job_id), None)
    if not started_job or started_job.get("status") == "stopped":
        return
    _log_activity(target_id, "job_started", "Started baseline enumeration.", {"job_id": job_id})

    with STATE_LOCK:
        target = _load_target(target_id)
        command, xml_path, text_path = _build_nmap_command(target, job_id)

    if shutil.which(command[0]) is None:
        def mark_missing_binary(missing_target: dict[str, Any]) -> None:
            for missing_job in missing_target["jobs"]:
                if missing_job["id"] == job_id:
                    missing_job["status"] = "failed"
                    missing_job["finished_at"] = _now()
                    missing_job["updated_at"] = _now()
                    missing_job["error"] = f"{command[0]} not found on PATH"
                    break
            missing_target["status"] = "error"
            missing_target["phase"] = "enumeration_failed"
            missing_target["latest_summary"] = f"Enumeration failed because {command[0]} is not installed."
            missing_target["timeline"].append(
                _timeline_event("job_failed", "Baseline enumeration could not start because nmap is unavailable.")
            )

        _with_target_lock(target_id, mark_missing_binary)
        _log_activity(target_id, "job_failed", "Enumeration binary missing.", {"binary": command[0]})
        return

    try:
        process = subprocess.Popen(
            command,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=1,
        )
        _set_execution_runtime("job", job_id, process=process, pid=process.pid, started_at=_now())

        def record_pid(job_target: dict[str, Any]) -> None:
            _update_execution_record(
                job_target,
                "job",
                job_id,
                lambda item: item.update({"pid": process.pid, "output_path": str(text_path), "updated_at": _now()}),
            )

        _with_target_lock(target_id, record_pid)
        _stream_process_output(target_id, "job", job_id, process, text_path, SCAN_TIMEOUT_SECONDS)
        return_code = process.wait(timeout=1)
        services, hostnames = _parse_nmap_xml(xml_path)
        runtime = _get_execution_runtime("job", job_id) or {}
        combined_output = runtime.get("tail", "")
        stopped = bool(runtime.get("stop_requested_at"))

        def mark_complete(completed_target: dict[str, Any]) -> None:
            pause_reasons: list[str] = []
            for completed_job in completed_target["jobs"]:
                if completed_job["id"] == job_id:
                    completed_job["status"] = "stopped" if stopped else ("completed" if return_code == 0 else "failed")
                    completed_job["finished_at"] = _now()
                    completed_job["updated_at"] = _now()
                    completed_job["return_code"] = return_code
                    completed_job["pid"] = process.pid
                    completed_job["termination_reason"] = runtime.get("termination_reason")
                    completed_job["live_output_tail"] = runtime.get("tail", "")
                    completed_job["output_bytes"] = runtime.get("output_bytes", 0)
                    completed_job["last_output_at"] = runtime.get("last_output_at")
                    completed_job["stop_requested_at"] = runtime.get("stop_requested_at")
                    completed_job["summary"] = (
                        f"Parsed {len(services)} open services from the baseline scan."
                        if return_code == 0 and not stopped
                        else "Baseline enumeration was stopped by the operator."
                        if stopped
                        else "nmap exited with a non-zero status."
                    )
                    completed_job["error"] = None if return_code == 0 or stopped else combined_output[-1200:]
                    break
            if not stopped:
                completed_target["services"] = services
                completed_target["hostnames"] = hostnames
            if return_code == 0 and not stopped:
                current_job = next((item for item in completed_target["jobs"] if item["id"] == job_id), None)
                if current_job is not None:
                    pause_reasons = _merge_action_intelligence(completed_target, current_job, combined_output)
            if return_code == 0 and not stopped:
                _refresh_agent_actions(completed_target)
            completed_target["findings"] = _build_findings(completed_target.get("services", []), completed_target.get("observations", []))
            if pause_reasons:
                completed_target.setdefault("autonomy", _default_autonomy_state())
                completed_target["autonomy"]["paused"] = True
                completed_target["autonomy"]["pause_reason"] = pause_reasons[-1]
                completed_target["autonomy"]["paused_at"] = _now()
            completed_target["latest_summary"] = "Baseline enumeration was stopped by the operator." if stopped else _compose_summary(completed_target)
            completed_target["status"] = "ready" if return_code == 0 or stopped else "error"
            completed_target["phase"] = "awaiting_approval" if stopped else ("enumerated" if return_code == 0 else "enumeration_failed")
            completed_target["timeline"].append(
                _timeline_event(
                    "job_stopped" if stopped else ("job_completed" if return_code == 0 else "job_failed"),
                    "Baseline enumeration was stopped by the operator." if stopped else ("Baseline enumeration finished." if return_code == 0 else "Baseline enumeration failed."),
                    {"job_id": job_id, "return_code": return_code, "pause_reasons": pause_reasons},
                )
            )

        _with_target_lock(target_id, mark_complete)
        _set_execution_runtime(
            "job",
            job_id,
            finished_at=_now(),
            return_code=return_code,
            process=None,
        )
        _log_activity(
            target_id,
            "job_stopped" if stopped else ("job_completed" if return_code == 0 else "job_failed"),
            "Baseline enumeration stopped." if stopped else "Baseline enumeration finished.",
            {"job_id": job_id, "return_code": return_code, "open_services": len(services)},
        )
        if return_code == 0 and not stopped:
            _dispatch_next_approved_action(target_id)
    except subprocess.TimeoutExpired:
        runtime = _get_execution_runtime("job", job_id) or {}
        stopped = bool(runtime.get("stop_requested_at"))

        def mark_timeout(timeout_target: dict[str, Any]) -> None:
            for timeout_job in timeout_target["jobs"]:
                if timeout_job["id"] == job_id:
                    timeout_job["status"] = "stopped" if stopped else "failed"
                    timeout_job["finished_at"] = _now()
                    timeout_job["updated_at"] = _now()
                    timeout_job["termination_reason"] = runtime.get("termination_reason")
                    timeout_job["live_output_tail"] = runtime.get("tail", "")
                    timeout_job["output_bytes"] = runtime.get("output_bytes", 0)
                    timeout_job["last_output_at"] = runtime.get("last_output_at")
                    timeout_job["stop_requested_at"] = runtime.get("stop_requested_at")
                    timeout_job["error"] = None if stopped else "Enumeration timed out"
                    timeout_job["summary"] = "Baseline enumeration was stopped by the operator." if stopped else "Enumeration timed out."
                    break
            timeout_target["status"] = "ready" if stopped else "error"
            timeout_target["phase"] = "awaiting_approval" if stopped else "enumeration_failed"
            timeout_target["latest_summary"] = "Baseline enumeration was stopped by the operator." if stopped else "Baseline enumeration timed out before completing."
            timeout_target["timeline"].append(
                _timeline_event("job_stopped" if stopped else "job_failed", "Baseline enumeration was stopped by the operator." if stopped else "Baseline enumeration timed out.", {"job_id": job_id})
            )

        _with_target_lock(target_id, mark_timeout)
        _set_execution_runtime("job", job_id, finished_at=_now(), return_code=None, process=None)
        _log_activity(target_id, "job_stopped" if stopped else "job_failed", "Baseline enumeration was stopped." if stopped else "Baseline enumeration timed out.", {"job_id": job_id})
    except Exception as exc:  # noqa: BLE001
        def mark_exception(error_target: dict[str, Any]) -> None:
            for error_job in error_target["jobs"]:
                if error_job["id"] == job_id:
                    error_job["status"] = "failed"
                    error_job["finished_at"] = _now()
                    error_job["updated_at"] = _now()
                    error_job["error"] = str(exc)
                    break
            error_target["status"] = "error"
            error_target["phase"] = "enumeration_failed"
            error_target["latest_summary"] = f"Baseline enumeration crashed: {exc}"
            error_target["timeline"].append(
                _timeline_event("job_failed", "Baseline enumeration crashed.", {"job_id": job_id, "error": str(exc)})
            )

        _with_target_lock(target_id, mark_exception)
        _log_activity(target_id, "job_failed", "Baseline enumeration crashed.", {"job_id": job_id, "error": str(exc)})


def _extract_http_observation(output: str, port: int | None = None) -> dict[str, Any]:
    server_match = re.search(r"^server:\s*(.+)$", output, flags=re.IGNORECASE | re.MULTILINE)
    title_match = re.search(r"<title>(.*?)</title>", output, flags=re.IGNORECASE | re.DOTALL)
    body_text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", output)).strip()
    snippet = body_text[:240] if body_text else "HTTP response captured."
    parts = []
    if server_match:
        parts.append(f"server header suggests {server_match.group(1).strip()}")
    if title_match:
        parts.append(f"title is '{title_match.group(1).strip()}'")
    if not parts and snippet:
        parts.append(snippet)
    return {
        "title": "HTTP fingerprint captured",
        "severity": "info",
        "summary": "; ".join(parts),
        "confidence": "observed",
        "port": port,
    }


def _extract_text_blob_observation(output: str, port: int | None = None) -> dict[str, Any]:
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    summary = " / ".join(lines[:4])[:280] if lines else "No metadata files were returned."
    return {
        "title": "HTTP metadata files checked",
        "severity": "info",
        "summary": summary,
        "confidence": "observed",
        "port": port,
    }


def _extract_smb_observation(output: str, port: int | None = None) -> dict[str, Any]:
    shares = re.findall(r"^\s*([A-Za-z0-9$_-]+)\s+Disk", output, flags=re.MULTILINE)
    if shares:
        summary = f"Anonymous SMB listing exposed shares: {', '.join(shares[:6])}"
        severity = "medium"
    else:
        summary = "Anonymous SMB listing did not reveal readable shares."
        severity = "info"
    return {
        "title": "SMB anonymous listing result",
        "severity": severity,
        "summary": summary,
        "confidence": "observed",
        "port": port,
    }


def _extract_dns_observation(output: str, port: int | None = None) -> dict[str, Any]:
    transfer_lines = [line for line in output.splitlines() if line and not line.startswith(";")]
    success = any("\tIN\t" in line for line in transfer_lines)
    summary = "DNS zone transfer returned records." if success else "DNS zone transfer did not return zone data."
    return {
        "title": "DNS AXFR result",
        "severity": "medium" if success else "info",
        "summary": summary,
        "confidence": "observed",
        "port": port,
    }


def _extract_nmap_text_observation(output: str) -> dict[str, Any]:
    open_ports = re.findall(r"^(\d+)/(tcp|udp)\s+open\s+([^\s]+)", output, flags=re.MULTILINE)
    if open_ports:
        listed = ", ".join(f"{port}/{proto} {svc}" for port, proto, svc in open_ports[:6])
        summary = f"Nmap text output confirmed: {listed}"
    else:
        summary = "Nmap text output completed."
    return {
        "title": "Nmap follow-up completed",
        "severity": "info",
        "summary": summary,
        "confidence": "observed",
        "port": None,
    }


def _surface_url_from_action(action: dict[str, Any]) -> str | None:
    match = re.search(r"https?://[^\s'\"<>]+", str(action.get("command") or ""))
    if match:
        return match.group(0).rstrip(".,)")
    return None


def _extract_credentials_from_output(action: dict[str, Any], output: str) -> list[dict[str, Any]]:
    credentials: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for username, password, code in re.findall(r"([A-Za-z0-9_.-]+):([^\s:]+)\s*->\s*(\d{3})", output):
        if code not in {"200", "204", "301", "302", "401", "403"}:
            continue
        key = (username, password)
        if key in seen:
            continue
        seen.add(key)
        credentials.append(
            {
                "id": _new_id("cred"),
                "label": f"{username}:{password}",
                "username": username,
                "password": password,
                "status": "validated" if code in {"200", "301", "302", "403"} else "candidate",
                "summary": f"{username}:{password} returned HTTP {code} during {action.get('label')}.",
                "confidence": "observed",
                "source_action_id": action.get("id"),
                "created_at": _now(),
                "updated_at": _now(),
            }
        )
    generic_patterns = [
        r"\b(?:user(?:name)?|login)\s*[:=]\s*([A-Za-z0-9_.-]+).{0,40}?(?:pass(?:word)?|pwd)\s*[:=]\s*([^\s]+)",
        r"\b(?:default\s+)?username\s+and\s+password\s+is\s+([A-Za-z0-9_.-]+)\s*(?:/|:)\s*([^\s<]+)",
        r"\blogin\s+with\s+([A-Za-z0-9_.-]+)\s*(?:/|:)\s*([^\s<]+)",
    ]
    for username, password in {
        match
        for pattern in generic_patterns
        for match in re.findall(pattern, output, flags=re.IGNORECASE | re.DOTALL)
    }:
        key = (username, password)
        if key in seen:
            continue
        seen.add(key)
        credentials.append(
            {
                "id": _new_id("cred"),
                "label": f"{username}:{password}",
                "username": username,
                "password": password,
                "status": "candidate",
                "summary": f"Parsed credential-like material from {action.get('label')}.",
                "confidence": "candidate",
                "source_action_id": action.get("id"),
                "created_at": _now(),
                "updated_at": _now(),
            }
        )
    return credentials


def _extract_session_records(action: dict[str, Any], output: str) -> list[dict[str, Any]]:
    session_markers = ("pwned", "meterpreter", "uid=", "whoami", "nt authority\\system", "root@", "/#")
    if not any(marker in output.lower() for marker in session_markers):
        return []
    prompt_match = re.search(r"([A-Za-z0-9_.-]+)@([A-Za-z0-9_.-]+):[^\n]*[#>$]", output)
    user_match = re.search(r"uid=\d+\(([^)]+)\)", output, flags=re.IGNORECASE)
    if user_match:
        user = user_match.group(1)
    elif "nt authority\\system" in output.lower():
        user = "SYSTEM"
    elif prompt_match:
        user = prompt_match.group(1)
    else:
        user = None
    host = prompt_match.group(2) if prompt_match else None
    if user:
        user = re.sub(r"^(?:x[0-9a-fA-F]{2})+", "", user)
        user = re.sub(r"^[^A-Za-z0-9_]+", "", user)
    label = action.get("label") or "session"
    if user and host:
        label = f"{user}@{host}"
    elif user:
        label = f"{user} session"
    return [
        {
            "id": _new_id("sess"),
            "label": label,
            "user": user,
            "host": host,
            "status": "active",
            "summary": f"Output from {action.get('label')} suggests command execution or session access.",
            "confidence": "candidate",
            "source_action_id": action.get("id"),
            "created_at": _now(),
        }
    ]


def _extract_web_surface(action: dict[str, Any], output: str) -> list[dict[str, Any]]:
    url = _surface_url_from_action(action)
    if not url:
        return []
    title_match = re.search(r"<title>(.*?)</title>", output, flags=re.IGNORECASE | re.DOTALL)
    return [
        {
            "id": _new_id("web"),
            "url": url,
            "label": title_match.group(1).strip() if title_match else url,
            "status": "observed",
            "summary": f"Observed through {action.get('label')}.",
            "confidence": "observed",
            "source_action_id": action.get("id"),
            "created_at": _now(),
        }
    ]


def _merge_action_intelligence(target: dict[str, Any], action: dict[str, Any], output: str) -> list[str]:
    pause_reasons: list[str] = []
    credentials = _extract_credentials_from_output(action, output)
    sessions = _extract_session_records(action, output)
    surfaces = _extract_web_surface(action, output)
    produced = set(action.get("produces") or [])

    for surface in surfaces:
        if not _entity_exists(target.get("web_surfaces", []), "url", str(surface.get("url") or "")):
            target.setdefault("web_surfaces", []).append(surface)
            _append_decision_journal(target, "Web surface observed", surface["summary"], kind="web_surface", evidence_id=surface["id"])

    for credential in credentials:
        if _entity_exists(target.get("credentials", []), "label", credential["label"]):
            continue
        target.setdefault("credentials", []).append(credential)
        target.setdefault("paths", []).append(
            {
                "id": _new_id("path"),
                "kind": "credential_path",
                "label": f"Credential candidate {credential['label']}",
                "status": credential["status"],
                "from_id": action.get("id"),
                "to_id": credential["id"],
                "created_at": _now(),
            }
        )
        _append_decision_journal(
            target,
            "Credential candidate harvested",
            credential["summary"],
            kind="credential",
            evidence_id=credential["id"],
            why_this_pivot="A candidate credential can unlock bounded auth checks on exposed services.",
            what_changed="The evidence model now includes a structured credential record.",
            what_would_stop="Autonomy can pause here if credential pause boundaries are enabled.",
        )
        if (target.get("autonomy") or {}).get("pause_on_credential"):
            pause_reasons.append(f"Paused after harvesting credential {credential['label']}.")

    for session in sessions:
        if _entity_exists(target.get("sessions", []), "label", str(session.get("label") or "")):
            continue
        credential_id = target.get("credentials", [])[-1]["id"] if target.get("credentials") else None
        if credential_id:
            session["credential_id"] = credential_id
        target.setdefault("sessions", []).append(session)
        _append_decision_journal(
            target,
            "Session indicator observed",
            session["summary"],
            kind="session",
            evidence_id=session["id"],
            why_this_pivot="The output suggests command execution or authenticated access.",
            what_changed="The target now has a structured session record for post-access workflows.",
            what_would_stop="Autonomy pauses on first session when that boundary is enabled.",
        )
        if (target.get("autonomy") or {}).get("pause_on_session"):
            pause_reasons.append("Paused after session creation or shell indicator.")

    if "privesc_signal" in produced and (target.get("autonomy") or {}).get("pause_on_privesc"):
        pause_reasons.append("Paused after a privilege-escalation probe was queued or completed.")
        target.setdefault("paths", []).append(
            {
                "id": _new_id("path"),
                "kind": "privesc_signal",
                "label": action.get("label") or "privesc",
                "status": "candidate",
                "from_id": action.get("id"),
                "to_id": host_id if (host_id := f"host:{target['ip_address']}") else None,
                "created_at": _now(),
            }
        )

    artifact_path = action.get("output_path")
    if artifact_path and not _entity_exists(target.get("artifacts", []), "path", str(artifact_path)):
        target.setdefault("artifacts", []).append(
            {
                "id": _new_id("artifact"),
                "label": action.get("label") or "artifact",
                "path": artifact_path,
                "kind": action.get("campaign") or "action",
                "source_action_id": action.get("id"),
                "created_at": _now(),
            }
        )
    return pause_reasons


def _retrofit_observed_intelligence(target: dict[str, Any]) -> None:
    completed_items = [
        *[item for item in target.get("jobs", []) if item.get("status") == "completed"],
        *[item for item in target.get("agent_actions", []) if item.get("status") == "completed"],
    ]
    for item in completed_items:
        output = str(item.get("live_output_tail") or item.get("result_excerpt") or "")
        if not output:
            output = _tail_text_from_path(item.get("output_path"))
        if not output:
            continue
        _merge_action_intelligence(
            target,
            {
                "id": item.get("id"),
                "label": item.get("label") or item.get("kind") or "completed operation",
                "output_path": item.get("output_path"),
                "campaign": item.get("kind") or item.get("campaign") or "historical",
                "produces": item.get("produces") or [],
            },
            output,
        )


def _parse_action_output(action: dict[str, Any], output: str) -> dict[str, Any]:
    port_match = re.search(r":(\d+)", action["command"])
    port = int(port_match.group(1)) if port_match else None
    parser = action["parser"]
    if parser == "http_response":
        return _extract_http_observation(output, port)
    if parser == "http_text_blobs":
        return _extract_text_blob_observation(output, port)
    if parser == "smbclient_listing":
        return _extract_smb_observation(output, port or 445)
    if parser == "dns_axfr":
        return _extract_dns_observation(output, port or 53)
    if parser == "nmap_text":
        return _extract_nmap_text_observation(output)
    if parser == "credential_probe":
        return {
            "title": "Credential validation result",
            "severity": "medium" if re.search(r"\b(200|302|\[\+\]|pwned)\b", output, flags=re.IGNORECASE) else "info",
            "summary": output[:280] if output else "Credential validation finished.",
            "confidence": "observed",
            "port": port,
        }
    if parser == "session_probe":
        return {
            "title": "Session environment check",
            "severity": "medium",
            "summary": output[:280] if output else "Session check completed.",
            "confidence": "observed",
            "port": port,
        }
    if parser == "privesc_probe":
        return {
            "title": "Privilege escalation probe",
            "severity": "medium",
            "summary": output[:280] if output else "Privesc probe completed.",
            "confidence": "observed",
            "port": port,
        }
    return {
        "title": action["label"],
        "severity": "info",
        "summary": output[:240] if output else "Command completed.",
        "confidence": "observed",
        "port": port,
    }


def _run_agent_action(target_id: str, action_id: str) -> None:
    try:
        def mark_running(target: dict[str, Any]) -> None:
            for action in target["agent_actions"]:
                if action["id"] == action_id:
                    if action["status"] == "stopped":
                        return
                    action["status"] = "running"
                    action["started_at"] = _now()
                    action["updated_at"] = _now()
                    break
            target["phase"] = "agent_action_running"
            target["timeline"].append(
                _timeline_event("action_started", "Approved agent action is running.", {"action_id": action_id})
            )

        target_after_start = _with_target_lock(target_id, mark_running)
        started_action = next((item for item in target_after_start["agent_actions"] if item["id"] == action_id), None)
        if not started_action or started_action.get("status") == "stopped":
            return
        _log_activity(target_id, "action_started", "Started approved action.", {"action_id": action_id})

        with STATE_LOCK:
            target = _load_target(target_id)
            action = next(item for item in target["agent_actions"] if item["id"] == action_id)
            command = action["command"]

        artifacts_dir = _artifacts_dir(target_id, "actions")
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        output_path = artifacts_dir / f"{action_id}.log"
        binary = _binary_for_command(command)
        if not _tool_available(binary):
            def mark_missing_tool(missing_target: dict[str, Any]) -> None:
                for action_item in missing_target["agent_actions"]:
                    if action_item["id"] == action_id:
                        action_item["status"] = "blocked"
                        action_item["finished_at"] = _now()
                        action_item["updated_at"] = _now()
                        action_item["error"] = f"{binary} is not installed"
                        break
                missing_target["phase"] = _resting_target_phase(missing_target)
                missing_target["latest_summary"] = f"Approved action could not run because {binary} is not installed."
                missing_target["timeline"].append(
                    _timeline_event("action_blocked", "Approved action is blocked by a missing tool.", {"action_id": action_id})
                )

            _with_target_lock(target_id, mark_missing_tool)
            _log_activity(target_id, "action_blocked", "Approved action blocked by missing tool.", {"action_id": action_id})
            return

        process = subprocess.Popen(
            command,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=1,
            shell=True,
        )
        _set_execution_runtime("action", action_id, process=process, pid=process.pid, started_at=_now())

        def record_pid(action_target: dict[str, Any]) -> None:
            _update_execution_record(
                action_target,
                "action",
                action_id,
                lambda item: item.update({"pid": process.pid, "output_path": str(output_path), "updated_at": _now()}),
            )

        _with_target_lock(target_id, record_pid)
        _stream_process_output(target_id, "action", action_id, process, output_path, ACTION_TIMEOUT_SECONDS)
        return_code = process.wait(timeout=1)
        runtime = _get_execution_runtime("action", action_id) or {}
        combined_output = runtime.get("tail", "")
        stopped = bool(runtime.get("stop_requested_at"))
        observation = _parse_action_output(action, combined_output)

        def mark_complete(completed_target: dict[str, Any]) -> None:
            pause_reasons: list[str] = []
            for action_item in completed_target["agent_actions"]:
                if action_item["id"] == action_id:
                    action_item["status"] = "stopped" if stopped else ("completed" if return_code == 0 else "failed")
                    action_item["finished_at"] = _now()
                    action_item["updated_at"] = _now()
                    action_item["output_path"] = str(output_path)
                    action_item["pid"] = process.pid
                    action_item["termination_reason"] = runtime.get("termination_reason")
                    action_item["live_output_tail"] = runtime.get("tail", "")
                    action_item["output_bytes"] = runtime.get("output_bytes", 0)
                    action_item["last_output_at"] = runtime.get("last_output_at")
                    action_item["stop_requested_at"] = runtime.get("stop_requested_at")
                    action_item["summary"] = observation["summary"]
                    action_item["parse_summary"] = "Approved action was stopped by the operator." if stopped else observation["summary"]
                    action_item["result_excerpt"] = combined_output[:600]
                    action_item["error"] = None if return_code == 0 or stopped else combined_output[-1200:]
                    if return_code == 0 and not stopped:
                        pause_reasons = _merge_action_intelligence(completed_target, action_item, combined_output)
                    break
            if not stopped:
                completed_target["observations"].append(observation)
            _refresh_agent_actions(completed_target)
            completed_target["findings"] = _build_findings(completed_target.get("services", []), completed_target["observations"])
            completed_target["phase"] = _resting_target_phase(completed_target)
            if pause_reasons:
                completed_target.setdefault("autonomy", _default_autonomy_state())
                completed_target["autonomy"]["paused"] = True
                completed_target["autonomy"]["pause_reason"] = pause_reasons[-1]
                completed_target["autonomy"]["paused_at"] = _now()
            completed_target["latest_summary"] = "Approved action was stopped by the operator." if stopped else _compose_summary(completed_target)
            completed_target["timeline"].append(
                _timeline_event(
                    "action_stopped" if stopped else ("action_completed" if return_code == 0 else "action_failed"),
                    "Approved agent action was stopped by the operator." if stopped else ("Approved agent action completed." if return_code == 0 else "Approved agent action failed."),
                    {"action_id": action_id, "return_code": return_code, "pause_reasons": pause_reasons},
                )
            )

        _with_target_lock(target_id, mark_complete)
        _set_execution_runtime(
            "action",
            action_id,
            finished_at=_now(),
            return_code=return_code,
            process=None,
        )
        _log_activity(
            target_id,
            "action_stopped" if stopped else ("action_completed" if return_code == 0 else "action_failed"),
            "Approved action stopped." if stopped else "Approved action finished.",
            {"action_id": action_id, "return_code": return_code, "summary": observation["summary"]},
        )
        _dispatch_next_approved_action(target_id)
    except subprocess.TimeoutExpired:
        runtime = _get_execution_runtime("action", action_id) or {}
        stopped = bool(runtime.get("stop_requested_at"))

        def mark_timeout(timeout_target: dict[str, Any]) -> None:
            for action_item in timeout_target["agent_actions"]:
                if action_item["id"] == action_id:
                    action_item["status"] = "stopped" if stopped else "failed"
                    action_item["finished_at"] = _now()
                    action_item["updated_at"] = _now()
                    action_item["termination_reason"] = runtime.get("termination_reason")
                    action_item["live_output_tail"] = runtime.get("tail", "")
                    action_item["output_bytes"] = runtime.get("output_bytes", 0)
                    action_item["last_output_at"] = runtime.get("last_output_at")
                    action_item["stop_requested_at"] = runtime.get("stop_requested_at")
                    action_item["parse_summary"] = "Approved action was stopped by the operator." if stopped else "Command timed out."
                    action_item["error"] = None if stopped else "Command timed out"
                    break
            timeout_target["phase"] = _resting_target_phase(timeout_target)
            timeout_target["latest_summary"] = "Approved action was stopped by the operator." if stopped else "An approved action timed out."
            timeout_target["timeline"].append(
                _timeline_event("action_stopped" if stopped else "action_failed", "Approved action was stopped by the operator." if stopped else "Approved action timed out.", {"action_id": action_id})
            )

        _with_target_lock(target_id, mark_timeout)
        _set_execution_runtime("action", action_id, finished_at=_now(), return_code=None, process=None)
        _log_activity(target_id, "action_stopped" if stopped else "action_failed", "Approved action was stopped." if stopped else "Approved action timed out.", {"action_id": action_id})
        _dispatch_next_approved_action(target_id)
    except Exception as exc:  # noqa: BLE001
        def mark_exception(error_target: dict[str, Any]) -> None:
            for action_item in error_target["agent_actions"]:
                if action_item["id"] == action_id:
                    action_item["status"] = "failed"
                    action_item["finished_at"] = _now()
                    action_item["updated_at"] = _now()
                    action_item["error"] = str(exc)
                    break
            error_target["phase"] = _resting_target_phase(error_target)
            error_target["latest_summary"] = f"Approved action crashed: {exc}"
            error_target["timeline"].append(
                _timeline_event("action_failed", "Approved action crashed.", {"action_id": action_id, "error": str(exc)})
            )

        _with_target_lock(target_id, mark_exception)
        _log_activity(target_id, "action_failed", "Approved action crashed.", {"action_id": action_id, "error": str(exc)})
        _dispatch_next_approved_action(target_id)


def _approve_action(target_id: str, action_id: str, note: str | None) -> dict[str, Any]:
    with STATE_LOCK:
        target = _load_target(target_id)
        if _action_is_active(target):
            raise HTTPException(status_code=409, detail="Another approved action is already running")
        action = next((item for item in target["agent_actions"] if item["id"] == action_id), None)
        if action is None:
            raise HTTPException(status_code=404, detail="Action not found")
        if action["status"] not in {"pending_approval", "blocked"}:
            raise HTTPException(status_code=409, detail=f"Action is not awaiting approval ({action['status']})")
        if not action["tool_available"]:
            raise HTTPException(status_code=409, detail=f"Required tool is unavailable: {action['binary']}")
        action["status"] = "approved"
        action["approved_at"] = _now()
        action["updated_at"] = _now()
        action["decision_note"] = note
        action["termination_reason"] = None
        action["stop_requested_at"] = None
        target["phase"] = "action_approved"
        target["timeline"].append(
            _timeline_event("action_approved", "User approved an agent action.", {"action_id": action_id, "note": note})
        )
        _save_target(target)

    _log_activity(target_id, "action_approved", "User approved action.", {"action_id": action_id, "note": note})
    threading.Thread(target=_run_agent_action, args=(target_id, action_id), daemon=True).start()
    return _load_target(target_id)


def _deny_action(target_id: str, action_id: str, note: str | None) -> dict[str, Any]:
    def mark_denied(target: dict[str, Any]) -> None:
        action = next((item for item in target["agent_actions"] if item["id"] == action_id), None)
        if action is None:
            raise HTTPException(status_code=404, detail="Action not found")
        if action["status"] not in {"pending_approval", "blocked"}:
            raise HTTPException(status_code=409, detail=f"Action is not awaiting approval ({action['status']})")
        action["status"] = "denied"
        action["denied_at"] = _now()
        action["updated_at"] = _now()
        action["decision_note"] = note
        target["phase"] = _resting_target_phase(target)
        target["latest_summary"] = _compose_summary(target)
        target["timeline"].append(
            _timeline_event("action_denied", "User denied an agent action.", {"action_id": action_id, "note": note})
        )

    saved = _with_target_lock(target_id, mark_denied)
    _log_activity(target_id, "action_denied", "User denied action.", {"action_id": action_id, "note": note})
    return saved


def _stop_job(target_id: str, job_id: str, note: str | None) -> dict[str, Any]:
    with STATE_LOCK:
        target = _load_target(target_id)
        job = next((item for item in target.get("jobs", []) if item["id"] == job_id), None)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        if job["status"] not in {"queued", "running", "stopping"}:
            raise HTTPException(status_code=409, detail=f"Job is not running ({job['status']})")
        if job["status"] == "queued":
            job["status"] = "stopped"
            job["finished_at"] = _now()
            job["updated_at"] = _now()
            job["summary"] = "Queued job was stopped before execution."
            job["termination_reason"] = "operator_stop_requested"
            job["stop_requested_at"] = _now()
            target["status"] = "ready"
            target["phase"] = "awaiting_approval"
            target["latest_summary"] = "Queued enumeration was stopped before it started."
            target["timeline"].append(
                _timeline_event("job_stopped", "Queued job was stopped before execution.", {"job_id": job_id, "note": note})
            )
            _save_target(target)
            _log_activity(target_id, "job_stopped", "Queued job stopped.", {"job_id": job_id, "note": note})
            return target
        job["status"] = "stopping"
        job["updated_at"] = _now()
        job["stop_requested_at"] = _now()
        job["termination_reason"] = "operator_stop_requested"
        target["latest_summary"] = "Stopping the active job."
        target["timeline"].append(
            _timeline_event("job_stop_requested", "Operator requested that a running job be stopped.", {"job_id": job_id, "note": note})
        )
        _save_target(target)

    _request_execution_stop("job", job_id)
    _log_activity(target_id, "job_stop_requested", "Stop requested for running job.", {"job_id": job_id, "note": note})
    return _load_target(target_id)


def _stop_action(target_id: str, action_id: str, note: str | None) -> dict[str, Any]:
    with STATE_LOCK:
        target = _load_target(target_id)
        action = next((item for item in target.get("agent_actions", []) if item["id"] == action_id), None)
        if action is None:
            raise HTTPException(status_code=404, detail="Action not found")
        if action["status"] not in {"approved", "running", "stopping"}:
            raise HTTPException(status_code=409, detail=f"Action is not running ({action['status']})")
        if action["status"] == "approved" and _get_execution_runtime("action", action_id) is None:
            action["status"] = "stopped"
            action["finished_at"] = _now()
            action["updated_at"] = _now()
            action["stop_requested_at"] = _now()
            action["termination_reason"] = "operator_stop_requested"
            action["parse_summary"] = "Approved action was stopped before execution started."
            target["phase"] = _resting_target_phase(target)
            target["latest_summary"] = "Approved action was stopped before it started."
            target["timeline"].append(
                _timeline_event("action_stopped", "Approved action was stopped before execution.", {"action_id": action_id, "note": note})
            )
            _save_target(target)
            _log_activity(target_id, "action_stopped", "Approved action stopped before execution.", {"action_id": action_id, "note": note})
            return target
        action["status"] = "stopping"
        action["updated_at"] = _now()
        action["stop_requested_at"] = _now()
        action["termination_reason"] = "operator_stop_requested"
        target["latest_summary"] = "Stopping the approved action."
        target["timeline"].append(
            _timeline_event("action_stop_requested", "Operator requested that a running action be stopped.", {"action_id": action_id, "note": note})
        )
        _save_target(target)

    _request_execution_stop("action", action_id)
    _log_activity(target_id, "action_stop_requested", "Stop requested for running action.", {"action_id": action_id, "note": note})
    return _load_target(target_id)


def _generic_prompt_recommendations(ip_address: str) -> list[dict[str, Any]]:
    dummy_target = {"ip_address": ip_address, "services": []}
    catalog = _action_catalog(dummy_target, [])
    synthetic = []
    for item in catalog:
        synthetic.append(
            {
                "id": _new_id("rec"),
                "label": item["label"],
                "risk": item["risk"],
                "why": item["reason"],
                "command": item["command"],
                "status": "pending_approval",
            }
        )
    return synthetic or _default_recommendations(ip_address)


def _llm_system_prompt() -> str:
    custom = _runtime_settings().get("system_prompt")
    if custom:
        return str(custom).strip()
    return (
        "You are HTB Mission Control's local red-team assistant. Work like a careful Hack The Box operator. "
        "Use only stored target evidence, keep commands approval-gated, and prefer the smallest evidence-backed next step. "
        "Methodology: 1) confirm coverage of the exposed services, 2) deepen per-service enumeration, 3) test only high-probability anonymous access or default credentials, "
        "4) escalate to focused content discovery such as ffuf or gobuster only after quieter checks, 5) preserve uncertainty and never invent findings. "
        "When you recommend the next step, explain the mindset shift in one sentence and avoid repeating work that target evidence already completed."
    )


def _build_llm_user_prompt(ip_address: str, operator_prompt: str, target_context: str) -> str:
    return f"Target IP: {ip_address}\nOperator request: {operator_prompt}\n\nCurrent target context:\n{target_context}"


def _planner_unresolved_actions(target: dict[str, Any]) -> list[dict[str, Any]]:
    unresolved_statuses = {"pending_approval", "blocked", "approved", "running", "stopping"}
    return [item for item in target.get("agent_actions", []) if item.get("status") in unresolved_statuses]


def _planner_should_skip_tick(target: dict[str, Any]) -> tuple[bool, str | None, int]:
    unresolved_count = len(_planner_unresolved_actions(target))
    autonomy = target.get("autonomy") or _default_autonomy_state()
    if autonomy.get("paused"):
        return True, f"Planner paused: {autonomy.get('pause_reason') or 'manual pause'}", unresolved_count
    if unresolved_count > PLANNER_MAX_UNRESOLVED_ACTIONS:
        return (
            True,
            f"Planner tick skipped: unresolved action cap exceeded ({unresolved_count}>{PLANNER_MAX_UNRESOLVED_ACTIONS}).",
            unresolved_count,
        )
    return False, None, unresolved_count


def _enforce_planner_llm_limits(target_id: str) -> None:
    global PLANNER_LLM_TOKEN_BUCKET, PLANNER_LLM_LAST_REFILL, PLANNER_LLM_INFLIGHT
    while True:
        wait_seconds = 0.0
        now = time.monotonic()
        with PLANNER_RUNTIME_LOCK:
            elapsed = max(0.0, now - PLANNER_LLM_LAST_REFILL)
            refill = elapsed * (PLANNER_GLOBAL_RPM / 60.0)
            if refill > 0:
                PLANNER_LLM_TOKEN_BUCKET = min(float(PLANNER_GLOBAL_RPM), PLANNER_LLM_TOKEN_BUCKET + refill)
                PLANNER_LLM_LAST_REFILL = now

            last_target_call = PLANNER_TARGET_LAST_LLM_AT.get(target_id)
            cooldown_remaining = 0.0 if last_target_call is None else max(0.0, PLANNER_TARGET_COOLDOWN_SECONDS - (now - last_target_call))

            if PLANNER_LLM_INFLIGHT >= PLANNER_INFLIGHT_LIMIT:
                wait_seconds = max(wait_seconds, 0.05)
            if PLANNER_LLM_TOKEN_BUCKET < 1.0:
                deficit = 1.0 - PLANNER_LLM_TOKEN_BUCKET
                wait_seconds = max(wait_seconds, deficit / max(PLANNER_GLOBAL_RPM / 60.0, 1e-6))
            if cooldown_remaining > 0.0:
                wait_seconds = max(wait_seconds, cooldown_remaining)

            if wait_seconds <= 0.0:
                PLANNER_LLM_TOKEN_BUCKET = max(0.0, PLANNER_LLM_TOKEN_BUCKET - 1.0)
                PLANNER_LLM_INFLIGHT += 1
                PLANNER_TARGET_LAST_LLM_AT[target_id] = now
                return

        time.sleep(min(wait_seconds, 0.5))


def _release_planner_llm_inflight() -> None:
    global PLANNER_LLM_INFLIGHT
    with PLANNER_RUNTIME_LOCK:
        PLANNER_LLM_INFLIGHT = max(0, PLANNER_LLM_INFLIGHT - 1)


def _context_snapshot(active_target: dict[str, Any] | None, payload: LlmPromptRequest) -> tuple[str, dict[str, int], list[dict[str, Any]]]:
    if active_target is None:
        return (
            "No stored target record exists yet.",
            {"services": 0, "findings": 0, "observations": 0, "pending_actions": 0, "timeline": 0, "context_blocks": 0},
            [],
        )

    sections = [
        {
            "target": {
                "id": active_target["id"],
                "ip_address": active_target["ip_address"],
                "display_name": active_target.get("display_name"),
                "phase": active_target.get("phase"),
                "summary": active_target.get("latest_summary", ""),
            }
        }
    ]
    snapshot = {"services": 0, "findings": 0, "observations": 0, "pending_actions": 0, "timeline": 0, "context_blocks": 0}

    if payload.include_services:
        services = active_target.get("services", [])
        sections.append({"services": services})
        snapshot["services"] = len(services)
    if payload.include_findings:
        findings = active_target.get("findings", [])[:12]
        sections.append({"findings": findings})
        snapshot["findings"] = len(findings)
    if payload.include_observations:
        observations = active_target.get("observations", [])[-12:]
        sections.append({"observations": observations})
        snapshot["observations"] = len(observations)
    if payload.include_pending_actions:
        pending_actions = [
            {
                "id": item["id"],
                "label": item["label"],
                "command": item["command"],
                "status": item["status"],
                "tool_available": item.get("tool_available"),
                "stage": item.get("stage"),
                "mindset": item.get("mindset"),
                "source": item.get("source"),
            }
            for item in active_target.get("agent_actions", [])
            if item.get("status") in {"pending_approval", "blocked", "approved", "running", "stopping"}
        ]
        sections.append({"pending_actions": pending_actions})
        snapshot["pending_actions"] = len(pending_actions)
    if payload.include_timeline:
        timeline = active_target.get("timeline", [])[-12:]
        sections.append({"timeline": timeline})
        snapshot["timeline"] = len(timeline)

    selected_ids = set(payload.context_block_ids)
    selected_blocks = [item for item in active_target.get("context_blocks", []) if item["id"] in selected_ids]
    if selected_blocks:
        sections.append(
            {
                "operator_context_blocks": [
                    {
                        "id": item["id"],
                        "title": item["title"],
                        "kind": item["kind"],
                        "content": item["content"],
                    }
                    for item in selected_blocks
                ]
            }
        )
        snapshot["context_blocks"] = len(selected_blocks)

    return json.dumps(sections, indent=2), snapshot, selected_blocks


def _recent_conversation_messages(active_target: dict[str, Any] | None, limit: int = 8) -> list[dict[str, str]]:
    if active_target is None:
        return []
    messages = []
    for item in active_target.get("conversation", [])[-limit:]:
        role = item.get("role")
        content = str(item.get("content") or "").strip()
        if role not in {"user", "assistant", "system"} or not content:
            continue
        messages.append({"role": role, "content": content})
    return messages


def _resolve_llm_model(requested_model: str) -> tuple[str | None, dict[str, Any]]:
    probe = _probe_ollama()
    default_model = str(_runtime_settings().get("default_model") or "auto").strip()
    normalized = (requested_model or default_model or "auto").strip()
    if normalized and normalized not in {"auto", "local-heuristic"}:
        return normalized, probe
    if probe.get("reachable") and probe.get("models"):
        return probe["models"][0], probe
    return None, probe


def _call_ollama_chat(model: str, messages: list[dict[str, str]]) -> dict[str, Any]:
    base_url = _resolved_ollama_base_url()
    if not base_url:
        raise RuntimeError("Ollama is not configured")
    runtime = _runtime_settings()
    body = json.dumps(
        {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": runtime.get("temperature", DEFAULT_LLM_SETTINGS["temperature"]),
                "num_ctx": runtime.get("num_ctx", DEFAULT_LLM_SETTINGS["num_ctx"]),
            },
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url}/api/chat",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=max(OLLAMA_TIMEOUT_SECONDS, 30.0)) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return {
        "model": payload.get("model") or model,
        "content": (payload.get("message", {}) or {}).get("content", "").strip(),
    }


def _best_web_url(active_target: dict[str, Any], operator_prompt: str) -> str | None:
    match = re.search(r"https?://[^\s'\"<>]+", operator_prompt, flags=re.IGNORECASE)
    if match:
        return match.group(0).rstrip(".,)")
    for service in active_target.get("services", []):
        service_name = (service.get("service") or "").lower()
        tunnel = (service.get("tunnel") or "").lower()
        port = int(service.get("port") or 0)
        is_web = service_name in {"http", "http-proxy", "https"} or tunnel == "ssl" or port in {80, 443, 8080, 8000, 8443}
        if not is_web:
            continue
        scheme = "https" if service_name == "https" or tunnel == "ssl" or port in {443, 8443} else "http"
        if port in {80, 443}:
            return f"{scheme}://{active_target['ip_address']}"
        return f"{scheme}://{active_target['ip_address']}:{port}"
    return None


def _requested_operator_actions(active_target: dict[str, Any], operator_prompt: str) -> list[dict[str, Any]]:
    prompt = operator_prompt.lower()
    templates: list[dict[str, Any]] = []
    web_url = _best_web_url(active_target, operator_prompt)

    if "sqlmap" in prompt:
        if web_url:
            templates.append(
                {
                    "label": "Run sqlmap against the current web surface",
                    "risk": "high",
                    "approval_required": True,
                    "reason": "The operator explicitly requested SQL injection testing, which should stay approval-gated.",
                    "command": f"sqlmap -u {shlex.quote(web_url)} --batch --random-agent --level 2 --risk 1",
                    "parser": "generic_text",
                    "category": "operator_sqlmap",
                    "stage": "focused-exploitation",
                    "priority": 70,
                    "mindset": "Move into exploit validation only after the operator explicitly asks for it.",
                    "source": "operator_prompt",
                }
            )
        else:
            templates.append(
                {
                    "label": "No HTTP target available for sqlmap yet",
                    "risk": "informational",
                    "approval_required": False,
                    "reason": "The operator asked for sqlmap, but current evidence does not include a web endpoint or URL.",
                    "command": "Gather a concrete HTTP URL before running sqlmap.",
                    "parser": "note",
                    "category": "operator_sqlmap_note",
                    "stage": "focused-exploitation",
                    "priority": 70,
                    "mindset": "Do not launch SQL testing without a real web target.",
                    "source": "operator_prompt",
                }
            )

    if any(token in prompt for token in {"source code", "page source", "html source", "analyze the webpage", "analyze source"}):
        if web_url:
            templates.append(
                {
                    "label": "Capture the current page source for analysis",
                    "risk": "safe",
                    "approval_required": True,
                    "reason": "The operator requested source review; capturing the HTML is a low-noise first step.",
                    "command": f"curl -skL --max-time 20 {shlex.quote(web_url)} | sed -n '1,260p'",
                    "parser": "http_text_blobs",
                    "category": "operator_page_source",
                    "stage": "web-fingerprint",
                    "priority": 18,
                    "mindset": "Capture the rendered source before making assumptions about the app.",
                    "source": "operator_prompt",
                }
            )
        else:
            templates.append(
                {
                    "label": "No HTTP target available for source analysis yet",
                    "risk": "informational",
                    "approval_required": False,
                    "reason": "Page-source analysis needs a specific web endpoint in current target evidence.",
                    "command": "Identify a reachable HTTP or HTTPS endpoint before pulling page source.",
                    "parser": "note",
                    "category": "operator_page_source_note",
                    "stage": "web-fingerprint",
                    "priority": 18,
                    "mindset": "Tie source analysis to a confirmed web surface.",
                    "source": "operator_prompt",
                }
            )

    return templates


def _assistant_fallback_response(
    active_target: dict[str, Any] | None,
    operator_prompt: str,
    context_counts: dict[str, int],
    queued_actions: list[dict[str, Any]],
    model_error: str | None = None,
) -> str:
    lines = []
    if active_target is None:
        lines.append("No stored target record exists yet. Start enumeration or attach target context before asking for execution guidance.")
    else:
        lines.append(
            f"{active_target['display_name']} is in `{active_target.get('phase', 'unknown')}`. {active_target.get('latest_summary', '').strip()}"
        )
    attached = ", ".join(f"{count} {name.replace('_', ' ')}" for name, count in context_counts.items() if count)
    if attached:
        lines.append(f"Attached context: {attached}.")
    if queued_actions:
        labels = ", ".join(item["label"] for item in queued_actions[:3])
        lines.append(f"I queued {len(queued_actions)} approval-gated action(s): {labels}. Review or approve them from the action queue.")
    elif "sqlmap" in operator_prompt.lower() or "source" in operator_prompt.lower():
        lines.append("I did not queue an action because the current evidence does not expose the required surface yet.")
    else:
        lines.append("No new terminal action was queued from this prompt. Existing recommendations remain available in the queue.")
    if model_error:
        lines.append(f"Model inference fell back to local heuristics: {model_error}")
    return "\n\n".join(lines)


def _append_conversation_message(
    active_target: dict[str, Any],
    role: str,
    content: str,
    *,
    model: str | None = None,
    context_snapshot: dict[str, Any] | None = None,
    queued_action_ids: list[str] | None = None,
) -> dict[str, Any]:
    message = {
        "id": _new_id("msg"),
        "role": role,
        "content": content,
        "model": model,
        "context_snapshot": context_snapshot or {},
        "queued_action_ids": queued_action_ids or [],
        "created_at": _now(),
    }
    active_target.setdefault("conversation", []).append(message)
    return message


def _llm_request_messages(*messages: dict[str, str]) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    for item in messages:
        role = str(item.get("role") or "user").strip() or "user"
        content = str(item.get("content") or "")
        normalized.append({"role": role, "content": content})
    return normalized


def _append_target_llm_call(
    target: dict[str, Any],
    *,
    call_id: str,
    kind: str,
    title: str,
    detail: str,
    model: str | None,
    request_messages: list[dict[str, str]],
    operator_prompt: str | None = None,
) -> dict[str, Any]:
    entry = {
        "id": call_id,
        "prompt_id": call_id,
        "kind": kind,
        "status": "running",
        "title": title,
        "detail": detail,
        "model": model,
        "operator_prompt": operator_prompt,
        "request_messages": request_messages,
        "response_text": "",
        "live_output_tail": "",
        "output_bytes": 0,
        "last_output_at": None,
        "created_at": _now(),
        "started_at": _now(),
        "updated_at": _now(),
        "finished_at": None,
        "message_id": None,
        "queued_action_ids": [],
        "attached_context": {},
        "model_error": None,
        "summary": None,
        "result_excerpt": "",
        "error": None,
        "pid": None,
        "stop_requested_at": None,
        "termination_reason": None,
    }
    target.setdefault("llm_calls", []).append(entry)
    target.setdefault("llm_agent", _default_llm_agent_state())
    target["llm_agent"]["last_prompt_at"] = entry["started_at"]
    return entry


def _update_target_llm_call(target: dict[str, Any], call_id: str, **updates: Any) -> dict[str, Any] | None:
    llm_call = next((item for item in target.get("llm_calls", []) if item.get("id") == call_id), None)
    if llm_call is None:
        return None
    llm_call.update(updates)
    llm_call["updated_at"] = _now()
    response_text = str(llm_call.get("response_text") or "")
    llm_call["live_output_tail"] = response_text
    llm_call["result_excerpt"] = response_text[:1200]
    llm_call["output_bytes"] = len(response_text.encode("utf-8"))
    target.setdefault("llm_agent", _default_llm_agent_state())
    if llm_call.get("status") in {"completed", "failed"}:
        target["llm_agent"]["last_response_at"] = llm_call.get("finished_at") or llm_call["updated_at"]
    return llm_call


def _record_llm_prompt(
    ip_address: str,
    model: str,
    operator_prompt: str,
    target: dict[str, Any] | None,
    target_context: str,
) -> dict[str, Any]:
    entry = {
        "id": _new_id("prompt"),
        "event": "prompt",
        "timestamp_utc": _now(),
        "model": model,
        "ip_address": ip_address,
        "target_id": target.get("id") if target else None,
        "system_prompt": _llm_system_prompt(),
        "user_prompt": _build_llm_user_prompt(ip_address, operator_prompt, target_context),
        "operator_prompt": operator_prompt,
    }
    _append_jsonl(_llm_prompts_log_path(), entry)
    return entry


def _record_llm_response(
    prompt_entry: dict[str, Any],
    *,
    response_content: str,
    queued_action_ids: list[str] | None = None,
    attached_context: dict[str, Any] | None = None,
    model_error: str | None = None,
) -> dict[str, Any]:
    entry = {
        **prompt_entry,
        "event": "response",
        "timestamp_utc": _now(),
        "response": {
            "content": response_content,
            "queued_action_ids": queued_action_ids or [],
            "attached_context": attached_context or {},
            "model_error": model_error,
        },
    }
    _append_jsonl(_llm_prompts_log_path(), entry)
    return entry


def _conversation_payload(active_target: dict[str, Any]) -> dict[str, Any]:
    return {
        "messages": active_target.get("conversation", []),
        "context_blocks": active_target.get("context_blocks", []),
    }


def _build_llm_response(payload: LlmPromptRequest) -> dict[str, Any]:
    target_hint = payload.ip_address.strip() if payload.ip_address else None
    active_target = _find_target(payload.target_id, target_hint)
    ip_address = _validate_ip((target_hint or active_target["ip_address"]).strip()) if (target_hint or active_target) else ""
    target_context, context_counts, selected_blocks = _context_snapshot(active_target, payload)
    resolved_model, probe = _resolve_llm_model(payload.model)
    prompt_entry = _record_llm_prompt(ip_address, resolved_model or "local-heuristic", payload.prompt, active_target, target_context)

    queued_actions: list[dict[str, Any]] = []
    user_message = None
    assistant_message = None
    assistant_content = ""
    model_error = None
    skip_planner_tick = False
    skip_reason = None
    llm_call_id = prompt_entry["id"]

    if active_target is not None:
        def mutate(target: dict[str, Any]) -> None:
            nonlocal queued_actions, user_message, skip_planner_tick, skip_reason
            user_message = _append_conversation_message(
                target,
                "user",
                payload.prompt,
                model=resolved_model or "local-heuristic",
                context_snapshot={
                    "attached": context_counts,
                    "context_block_ids": [item["id"] for item in selected_blocks],
                },
            )
            queued_actions = _append_action_templates(target, _requested_operator_actions(target, payload.prompt))
            skip_planner_tick, skip_reason, unresolved_count = _planner_should_skip_tick(target)
            if skip_planner_tick:
                target["timeline"].append(
                    _timeline_event(
                        "planner_tick_skipped",
                        skip_reason or "Planner tick skipped.",
                        {"unresolved_actions": unresolved_count, "max_unresolved_actions": PLANNER_MAX_UNRESOLVED_ACTIONS},
                    )
                )
            else:
                _refresh_agent_actions(target)

        active_target = _with_target_lock(active_target["id"], mutate)

    request_messages: list[dict[str, str]] = []
    if resolved_model and active_target is not None:
        try:
            history = _recent_conversation_messages(active_target)
            if history and history[-1]["role"] == "user" and history[-1]["content"] == payload.prompt:
                history = history[:-1]
            request_messages = _llm_request_messages(
                {"role": "system", "content": _llm_system_prompt()},
                {"role": "system", "content": f"Current target context:\n{target_context}"},
                *history,
                {"role": "user", "content": payload.prompt},
            )
            active_target = _with_target_lock(
                active_target["id"],
                lambda target: _append_target_llm_call(
                    target,
                    call_id=llm_call_id,
                    kind="operator",
                    title="Operator LLM request",
                    detail=payload.prompt[:220],
                    model=resolved_model or "local-heuristic",
                    request_messages=request_messages,
                    operator_prompt=payload.prompt,
                ),
            )
            with _PlannerLlmPermit(active_target.get("id")):
                response = _call_ollama_chat(resolved_model, request_messages)
            assistant_content = response["content"] or ""
            resolved_model = response["model"] or resolved_model
        except Exception as exc:  # noqa: BLE001
            model_error = str(exc)
    elif active_target is not None:
        request_messages = _llm_request_messages(
            {"role": "system", "content": _llm_system_prompt()},
            {"role": "system", "content": f"Current target context:\n{target_context}"},
            {"role": "user", "content": payload.prompt},
        )
        active_target = _with_target_lock(
            active_target["id"],
            lambda target: _append_target_llm_call(
                target,
                call_id=llm_call_id,
                kind="operator",
                title="Operator LLM request",
                detail=payload.prompt[:220],
                model=resolved_model or "local-heuristic",
                request_messages=request_messages,
                operator_prompt=payload.prompt,
            ),
        )

    if not assistant_content:
        assistant_content = _assistant_fallback_response(active_target, payload.prompt, context_counts, queued_actions, model_error)

    if active_target is not None:
        def append_reply(target: dict[str, Any]) -> None:
            nonlocal assistant_message
            assistant_message = _append_conversation_message(
                target,
                "assistant",
                assistant_content,
                model=resolved_model or "local-heuristic",
                context_snapshot={
                    "attached": context_counts,
                    "context_block_ids": [item["id"] for item in selected_blocks],
                },
                queued_action_ids=[item["id"] for item in queued_actions],
            )
            _update_target_llm_call(
                target,
                llm_call_id,
                status="completed",
                finished_at=_now(),
                last_output_at=_now(),
                model=resolved_model or "local-heuristic",
                response_text=assistant_content,
                message_id=assistant_message["id"] if assistant_message else None,
                queued_action_ids=[item["id"] for item in queued_actions],
                attached_context=context_counts,
                model_error=model_error,
                error=model_error,
                termination_reason="model_error_fallback" if model_error else None,
                summary=(
                    "Model call failed and a local heuristic fallback generated the response shown below."
                    if model_error
                    else "Recorded the full prompt transcript and model response for this assistant turn."
                ),
            )
            target["latest_summary"] = _compose_summary(target)
            target["timeline"].append(
                _timeline_event(
                    "conversation_turn",
                    "Operator sent a chat prompt to the mission assistant.",
                    {"prompt_id": prompt_entry["id"], "message_id": assistant_message["id"] if assistant_message else None},
                )
            )

        active_target = _with_target_lock(active_target["id"], append_reply)
        _record_llm_response(
            prompt_entry,
            response_content=assistant_content,
            queued_action_ids=[item["id"] for item in queued_actions],
            attached_context=context_counts,
            model_error=model_error,
        )
        _dispatch_next_approved_action(active_target["id"])

    recommendations = active_target.get("recommendations", []) if active_target is not None else _generic_prompt_recommendations(ip_address)
    summary = active_target.get("latest_summary", "") if active_target is not None else "No stored target context yet. Start baseline enumeration first."
    return {
        "ok": True,
        "ip_address": ip_address,
        "target_id": active_target.get("id") if active_target else None,
        "prompt_id": prompt_entry["id"],
        "message": assistant_message,
        "conversation": _conversation_payload(active_target) if active_target is not None else {"messages": [], "context_blocks": []},
        "llm": {
            "summary": summary,
            "response": assistant_content,
            "model": resolved_model or "local-heuristic",
            "tool_calls": recommendations,
            "queued_actions": queued_actions,
            "attached_context": context_counts,
            "cautions": [
                "This response is grounded in stored target evidence and attached notes; validate any weak inference.",
                "Terminal actions stay approval-gated and run through the standard mission-control queue.",
            ],
            "model_status": probe,
        },
        "user_message": user_message,
    }


def _recent_llm_prompts(limit: int = 20) -> list[dict[str, Any]]:
    log_path = _llm_prompts_log_path()
    if not log_path.exists():
        return []
    lines = log_path.read_text(encoding="utf-8").splitlines()
    entries = [json.loads(line) for line in lines]
    prompts = [item for item in entries if item.get("event", "prompt") == "prompt"]
    return prompts[-max(1, min(limit, 100)):]


def _llm_prompts_payload(limit: int = 20) -> dict[str, Any]:
    return {
        "system_prompt": _llm_system_prompt(),
        "user_prompt_template": "Target IP: {ip_address}\\nOperator request: {operator_prompt}\\n\\nCurrent target context:\\n{target_context_json}",
        "prompt_log_path": str(_llm_prompts_log_path()),
        "recent_prompts": _recent_llm_prompts(limit),
    }


def _severity_counts(items: list[dict[str, Any]], key: str = "severity") -> dict[str, int]:
    counts = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}
    for item in items:
        severity = str(item.get(key) or "info").lower()
        if severity not in counts:
            severity = "info"
        counts[severity] += 1
    return counts


def _planner_candidate_templates(target: dict[str, Any]) -> list[dict[str, Any]]:
    existing_signatures = {
        _action_signature(item)
        for item in target.get("agent_actions", [])
        if item.get("status") not in {"denied", "removed", "failed", "completed", "informational"}
    }
    candidates: list[dict[str, Any]] = []
    for template in [*_action_catalog(target, target.get("services", [])), *_attack_engine_action_templates(target)]:
        allowed, _ = _action_policy_verdict(target, template)
        signature = f"{template['category']}::{template['command']}"
        if not allowed or signature in existing_signatures:
            continue
        candidates.append(template)
    return sorted(candidates, key=lambda item: (int(item.get("priority", 50)), item.get("label", "")))


def _target_report(target: dict[str, Any]) -> dict[str, Any]:
    services = target.get("services", [])
    findings = target.get("findings", [])
    observations = target.get("observations", [])
    actions = target.get("agent_actions", [])
    jobs = target.get("jobs", [])
    pending_actions = [item for item in actions if item.get("status") in {"pending_approval", "blocked"}]
    completed_actions = [item for item in actions if item.get("status") == "completed"]
    failed_actions = [item for item in actions if item.get("status") == "failed"]
    artifacts = [
        item.get("output_path")
        for item in [*jobs, *actions]
        if item.get("output_path")
    ]
    return {
        "id": target["id"],
        "ip_address": target["ip_address"],
        "display_name": target.get("display_name"),
        "phase": target.get("phase"),
        "status": target.get("status"),
        "objective_phase": _current_objective_phase(target),
        "updated_at": target.get("updated_at"),
        "summary": target.get("latest_summary", ""),
        "counts": {
            "services": len(services),
            "findings": len(findings),
            "observations": len(observations),
            "jobs": len(jobs),
            "pending_actions": len(pending_actions),
            "completed_actions": len(completed_actions),
            "failed_actions": len(failed_actions),
            "artifacts": len(artifacts),
            "credentials": len(target.get("credentials", [])),
            "sessions": len(target.get("sessions", [])),
            "paths": len(target.get("paths", [])),
        },
        "severity_counts": _severity_counts(findings),
        "action_status_counts": {
            "pending_approval": len(pending_actions),
            "completed": len(completed_actions),
            "failed": len(failed_actions),
            "blocked": len([item for item in actions if item.get("status") == "blocked"]),
            "running": len([item for item in actions if item.get("status") == "running"]),
            "informational": len([item for item in actions if item.get("status") == "informational"]),
        },
        "services": services,
        "top_findings": findings[:8],
        "latest_observations": observations[-8:],
        "artifacts": artifacts,
        "credentials": target.get("credentials", []),
        "sessions": target.get("sessions", []),
        "objectives": target.get("objectives", _default_objectives()),
        "attack_graph": target.get("attack_graph", _default_attack_graph(target["ip_address"])),
        "best_path": target.get("best_path"),
        "decision_journal": target.get("decision_journal", [])[-12:],
        "autonomy": target.get("autonomy", _default_autonomy_state()),
    }


def _planner_target_overloaded(target: dict[str, Any]) -> bool:
    unresolved_count = len(_planner_unresolved_actions(target))
    return unresolved_count >= PLANNER_MAX_PENDING_ACTIONS or _job_is_active(target) or _action_is_active(target)


def _planner_eligible_targets() -> list[str]:
    if not _runtime_settings().get("autoplan_enabled", False):
        return []
    eligible: list[str] = []
    with STATE_LOCK:
        for summary in _list_targets():
            target = _load_target(summary["id"])
            if target.get("deleted_at"):
                continue
            if target.get("status") not in {"ready", "enumerating"}:
                continue
            if _planner_target_overloaded(target):
                continue
            eligible.append(target["id"])
    return eligible


def _planner_prompt(target: dict[str, Any], context_blob: str, candidates: list[dict[str, Any]]) -> str:
    return (
        "Planner mode: you are ranking pre-approved local candidate actions for an HTB operator. "
        "Do not invent new commands. Return strict JSON with keys: hypothesis, selected_labels, rejected_labels. "
        f"Target: {target.get('display_name') or target['ip_address']}\n"
        f"Current objective: {_current_objective_phase(target)}\n"
        f"Context:\n{context_blob}\n\n"
        f"Candidates:\n{json.dumps([{key: item.get(key) for key in ['label', 'stage', 'reason', 'priority', 'campaign', 'noise_level', 'requires', 'produces']} for item in candidates], indent=2)}"
    )


def _parse_planner_actions(raw_content: str) -> list[dict[str, Any]]:
    if not raw_content:
        return []
    text = raw_content.strip()
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        text = match.group(0)
    payload = json.loads(text)
    if not isinstance(payload, dict):
        return []
    actions = payload.get("actions")
    if not isinstance(actions, list):
        return []
    parsed: list[dict[str, Any]] = []
    priority_map = {"critical": 90, "high": 75, "medium": 50, "low": 25, "info": 10}
    for item in actions[:2]:
        if not isinstance(item, dict):
            continue
        command = str(item.get("command") or "").strip()
        label = str(item.get("label") or "").strip()
        if not command or not label:
            continue
        raw_priority = item.get("priority")
        try:
            priority = int(raw_priority if raw_priority is not None else 50)
        except (TypeError, ValueError):
            priority = priority_map.get(str(raw_priority or "").strip().lower(), 50)
        parsed.append(
            {
                "label": label[:120],
                "risk": str(item.get("risk") or "safe"),
                "approval_required": True,
                "reason": str(item.get("reason") or "Planner suggested the next evidence-backed step."),
                "command": command,
                "parser": str(item.get("parser") or "generic_text"),
                "category": str(item.get("category") or "planner_generated"),
                "stage": str(item.get("stage") or "general"),
                "priority": priority,
                "mindset": str(item.get("mindset") or "Advance one concrete hypothesis with minimal noise."),
                "source": "planner_runtime",
            }
        )
    return parsed


def _planner_tick_target(target_id: str) -> None:
    target = _load_target(target_id)
    _log_activity(target_id, "planner_tick_started", "Planner tick started.", {"target_id": target_id})
    _planner_log("planner_tick_started", "Planner tick started.", {"target_id": target_id})
    skip_tick, skip_reason, unresolved_count = _planner_should_skip_tick(target)
    if skip_tick:
        def mark_skipped(locked_target: dict[str, Any]) -> None:
            locked_target.setdefault("timeline", []).append(
                _timeline_event(
                    "planner_tick_skipped",
                    skip_reason or "Planner tick skipped.",
                    {"unresolved_actions": unresolved_count, "max_unresolved_actions": PLANNER_MAX_UNRESOLVED_ACTIONS},
                )
            )

        _with_target_lock(target_id, mark_skipped)
        _log_activity(
            target_id,
            "planner_tick_skipped",
            skip_reason or "Planner tick skipped.",
            {"unresolved_actions": unresolved_count, "max_unresolved_actions": PLANNER_MAX_UNRESOLVED_ACTIONS},
        )
        _planner_log("planner_tick_skipped", skip_reason or "Planner tick skipped.", {"target_id": target_id})
        return

    context_blob, _, _ = _context_snapshot(target, LlmPromptRequest(target_id=target_id, prompt="planner", include_timeline=True))
    candidates = _planner_candidate_templates(target)
    if not candidates:
        _log_activity(target_id, "planner_noop", "Planner found no policy-eligible actions.", {})
        _planner_log("planner_noop", "Planner found no policy-eligible actions.", {"target_id": target_id})
        return
    model, _ = _resolve_llm_model("auto")
    prompt_id = _new_id("prompt")
    planner_request_messages = _llm_request_messages(
        {"role": "system", "content": _llm_system_prompt()},
        {"role": "user", "content": _planner_prompt(target, context_blob, candidates[:8])},
    )
    _with_target_lock(
        target_id,
        lambda locked_target: _append_target_llm_call(
            locked_target,
            call_id=prompt_id,
            kind="planner",
            title="Planner LLM decision",
            detail="Autonomy evaluated the current target context and ranked next-step actions.",
            model=model or "local-heuristic",
            request_messages=planner_request_messages,
        ),
    )
    try:
        queued_actions: list[dict[str, Any]] = []
        selected_labels: list[str] = []
        rejected_labels: list[str] = []
        hypothesis = "Local priority sort selected the next smallest useful steps."
        model_error = None
        raw_content = ""
        if model:
            with _PlannerLlmPermit(target_id):
                response = _call_ollama_chat(model, planner_request_messages)
            raw_content = response.get("content", "").strip()
            hypothesis_match = re.search(r'"hypothesis"\s*:\s*"([^"]+)"', raw_content)
            if hypothesis_match:
                hypothesis = hypothesis_match.group(1)
            selected_labels = re.findall(r'"selected_labels"\s*:\s*\[(.*?)\]', raw_content, flags=re.DOTALL)
            rejected_labels = re.findall(r'"rejected_labels"\s*:\s*\[(.*?)\]', raw_content, flags=re.DOTALL)
        selected_candidates = candidates[: max(1, min(int(_runtime_settings().get("autoplan_max_actions_per_turn", 2)), 4))]
        if selected_labels:
            normalized = {
                label.strip().strip('"').strip("'")
                for label in re.findall(r'"([^"]+)"', selected_labels[0])
            }
            ranked = [item for item in candidates if item["label"] in normalized]
            if ranked:
                selected_candidates = ranked[: max(1, min(int(_runtime_settings().get("autoplan_max_actions_per_turn", 2)), 4))]
        if rejected_labels:
            rejected_labels = [label.strip().strip('"').strip("'") for label in re.findall(r'"([^"]+)"', rejected_labels[0])]

        def mutate(locked_target: dict[str, Any]) -> None:
            nonlocal queued_actions
            queued_actions = _append_action_templates(locked_target, selected_candidates)
            locked_target.setdefault("autonomy", _default_autonomy_state())
            locked_target["autonomy"]["last_decision_at"] = _now()
            locked_target["autonomy"]["last_selected_path_id"] = (locked_target.get("best_path") or {}).get("id")
            _update_target_llm_call(
                locked_target,
                prompt_id,
                status="completed",
                finished_at=_now(),
                last_output_at=_now(),
                model=model or "local-heuristic",
                response_text=raw_content or hypothesis,
                queued_action_ids=[item.get("id") for item in queued_actions],
                attached_context={
                    "candidate_count": len(candidates),
                    "selected_count": len(selected_candidates),
                },
                model_error=model_error,
                error=model_error,
                termination_reason="model_error_fallback" if model_error else None,
                summary="Recorded the planner prompt and response so the Jobs pane can replay autonomy decisions.",
            )
            _append_decision_journal(
                locked_target,
                "Autonomy decision",
                hypothesis,
                kind="planner_turn",
                observed_evidence=context_blob[:2000],
                selected_path=locked_target.get("best_path"),
                selected_actions=[item.get("label") for item in queued_actions],
                rejected_alternatives=rejected_labels or [item["label"] for item in candidates[2:6]],
                what_changed="Autonomy queued the next command bundle under local policy.",
                what_would_stop=locked_target["autonomy"].get("pause_reason") or "Credential, session, privesc, or noise thresholds can pause the loop.",
            )
            if queued_actions:
                locked_target.setdefault("timeline", []).append(
                    _timeline_event(
                        "planner_actions_queued",
                        "Planner queued approval-gated actions.",
                        {"count": len(queued_actions), "action_ids": [a.get("id") for a in queued_actions]},
                    )
                )

        _with_target_lock(target_id, mutate)
        if queued_actions:
            _log_activity(
                target_id,
                "planner_actions_queued",
                "Planner queued actions.",
                {"count": len(queued_actions), "action_ids": [a.get("id") for a in queued_actions]},
            )
            _planner_log(
                "planner_actions_queued",
                "Planner queued actions.",
                {"target_id": target_id, "prompt_id": prompt_id, "model": model, "action_ids": [a.get("id") for a in queued_actions]},
            )
        else:
            _log_activity(target_id, "planner_noop", "Planner found no new actions.", {})
            _planner_log("planner_noop", "Planner found no new actions.", {"target_id": target_id, "prompt_id": prompt_id, "model": model})
    except Exception as exc:
        _with_target_lock(
            target_id,
            lambda locked_target: _update_target_llm_call(
                locked_target,
                prompt_id,
                status="failed",
                finished_at=_now(),
                last_output_at=_now(),
                model=model or "local-heuristic",
                response_text="",
                model_error=str(exc),
                error=str(exc),
                termination_reason="planner_llm_error",
                summary="Planner LLM call failed before a usable response was recorded.",
            ),
        )
        _log_activity(target_id, "planner_error", "Planner tick failed.", {"error": str(exc)})
        _planner_log("planner_error", "Planner tick failed.", {"target_id": target_id, "prompt_id": prompt_id, "model": model, "error": str(exc)})


def _planner_loop() -> None:
    while not PLANNER_STOP_EVENT.wait(max(5.0, PLANNER_INTERVAL_SECONDS)):
        for target_id in _planner_eligible_targets():
            if PLANNER_STOP_EVENT.is_set():
                return
            _planner_tick_target(target_id)


def _start_planner_runtime() -> None:
    global PLANNER_THREAD
    if PLANNER_THREAD and PLANNER_THREAD.is_alive():
        return
    PLANNER_STOP_EVENT.clear()
    PLANNER_THREAD = threading.Thread(target=_planner_loop, name="htbmc-planner", daemon=True)
    PLANNER_THREAD.start()


def _stop_planner_runtime() -> None:
    global PLANNER_THREAD
    PLANNER_STOP_EVENT.set()
    thread = PLANNER_THREAD
    if thread and thread.is_alive():
        thread.join(timeout=3)
    PLANNER_THREAD = None


@app.on_event("startup")
def _app_startup() -> None:
    _clear_past_runs()
    _apply_runtime_settings(_runtime_settings())
    if _runtime_settings().get("autoplan_enabled"):
        _start_planner_runtime()


@app.on_event("shutdown")
def _app_shutdown() -> None:
    _stop_planner_runtime()


def _settings_payload() -> dict[str, Any]:
    runtime = _runtime_settings()
    return {
        "state_dir": str(STATE_DIR),
        "targets_dir": str(TARGETS_DIR),
        "nmap_bin": NMAP_BIN,
        "nmap_path": shutil.which(NMAP_BIN),
        "scan_timeout_seconds": SCAN_TIMEOUT_SECONDS,
        "action_timeout_seconds": ACTION_TIMEOUT_SECONDS,
        "ollama_base_url": _resolved_ollama_base_url(),
        "ollama_timeout_seconds": OLLAMA_TIMEOUT_SECONDS,
        "llm": runtime,
        "planner": {
            "interval_seconds": PLANNER_INTERVAL_SECONDS,
            "max_pending_actions": PLANNER_MAX_PENDING_ACTIONS,
            "global_rpm": PLANNER_GLOBAL_RPM,
            "inflight_limit": PLANNER_INFLIGHT_LIMIT,
            "target_cooldown_seconds": PLANNER_TARGET_COOLDOWN_SECONDS,
            "max_unresolved_actions": PLANNER_MAX_UNRESOLVED_ACTIONS,
        },
        "cors": {"allow_origins": ["*"], "allow_credentials": False},
    }


def _resolved_ollama_base_url() -> str | None:
    runtime = _runtime_settings()
    base_url = str(runtime.get("ollama_base_url") or OLLAMA_BASE_URL or "").strip()
    tailscale_host = str(runtime.get("ollama_tailscale_host") or OLLAMA_TAILSCALE_HOST or "").strip()
    if base_url:
        return base_url.rstrip("/")
    if tailscale_host:
        return f"http://{tailscale_host}:11434"
    return None


def _probe_ollama() -> dict[str, Any]:
    base_url = _resolved_ollama_base_url()
    if not base_url:
        return {
            "configured": False,
            "reachable": False,
            "base_url": None,
            "models": [],
            "error": "Set OLLAMA_BASE_URL or OLLAMA_TAILSCALE_HOST to enable remote model checks.",
        }

    request = urllib.request.Request(f"{base_url}/api/tags", method="GET")
    try:
        with urllib.request.urlopen(request, timeout=OLLAMA_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        return {
            "configured": True,
            "reachable": False,
            "base_url": base_url,
            "models": [],
            "error": str(exc.reason if hasattr(exc, "reason") else exc),
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "configured": True,
            "reachable": False,
            "base_url": base_url,
            "models": [],
            "error": str(exc),
        }

    models = payload.get("models", [])
    return {
        "configured": True,
        "reachable": True,
        "base_url": base_url,
        "models": [item.get("name", "") for item in models if item.get("name")],
        "error": None,
    }


def _model_catalog_payload() -> dict[str, Any]:
    probe = _probe_ollama()
    return {
        "configured": probe["configured"],
        "reachable": probe["reachable"],
        "base_url": probe["base_url"],
        "endpoint": f"{probe['base_url']}/api/tags" if probe.get("base_url") else None,
        "models": probe.get("models", []),
        "error": probe.get("error"),
    }


def _planner_status() -> dict[str, Any]:
    targets = []
    for target_id in _planner_eligible_targets():
        target = _load_target(target_id)
        targets.append(
            {
                "target_id": target_id,
                "display_name": target.get("display_name") or target.get("ip_address"),
                "llm_agent": target.get("llm_agent", {}),
                "autonomy": target.get("autonomy", _default_autonomy_state()),
                "objective_phase": _current_objective_phase(target),
            }
        )
    return {
        "enabled": bool(_runtime_settings().get("autoplan_enabled", False)),
        "worker_alive": bool(PLANNER_THREAD and PLANNER_THREAD.is_alive()),
        "targets": targets,
        "planner_log_path": str(PLANNER_LOG_PATH),
    }


_ensure_dirs()


@app.get("/")
def root() -> dict[str, str]:
    return {"status": "ok", "service": "htb-mission-control"}


@app.get("/healthz")
def healthz() -> dict[str, Any]:
    ollama = _probe_ollama()
    return {
        "status": "healthy",
        "state_dir": str(STATE_DIR),
        "nmap_bin": shutil.which(NMAP_BIN),
        "targets": len(_list_targets()),
        "ollama": ollama,
    }


@app.get("/api/settings")
def get_settings() -> dict[str, Any]:
    return {"ok": True, "settings": _settings_payload(), "ollama": _probe_ollama()}


@app.get("/api/settings/models")
def get_settings_models() -> dict[str, Any]:
    return {"ok": True, "model_catalog": _model_catalog_payload()}


@app.post("/api/settings/llm")
def save_llm_settings(payload: LlmSettingsInput) -> dict[str, Any]:
    next_settings = {
        "ollama_base_url": payload.ollama_base_url,
        "ollama_tailscale_host": payload.ollama_tailscale_host,
        "ollama_timeout_seconds": payload.ollama_timeout_seconds,
        "default_model": payload.default_model,
        "temperature": payload.temperature,
        "num_ctx": payload.num_ctx,
        "autoplan_enabled": payload.autoplan_enabled,
        "autoplan_interval_seconds": payload.autoplan_interval_seconds,
        "autoplan_max_actions_per_turn": payload.autoplan_max_actions_per_turn,
        "autoplan_include_timeline": payload.autoplan_include_timeline,
        "autoplan_include_execution_history": payload.autoplan_include_execution_history,
        "autoplan_prompt": payload.autoplan_prompt,
        "system_prompt": payload.system_prompt,
        "autonomy_profile": payload.autonomy_profile,
        "autonomy_pause_on_credential": payload.autonomy_pause_on_credential,
        "autonomy_pause_on_session": payload.autonomy_pause_on_session,
        "autonomy_pause_on_privesc": payload.autonomy_pause_on_privesc,
        "autonomy_max_noise": payload.autonomy_max_noise,
    }
    if payload.command_allowlist is not None:
        next_settings["command_allowlist"] = payload.command_allowlist
    settings = _save_runtime_settings(next_settings)
    if settings.get("autoplan_enabled"):
        _start_planner_runtime()
    else:
        _stop_planner_runtime()
    return {
        "ok": True,
        "settings": _settings_payload(),
        "ollama": _probe_ollama(),
        "model_catalog": _model_catalog_payload(),
        "planner": _planner_status(),
    }


@app.get("/api/reports/overview")
def reports_overview() -> dict[str, Any]:
    targets = [_load_target(item["id"]) for item in _list_targets()]
    reports = [_target_report(target) for target in targets]
    return {
        "ok": True,
        "generated_at": _now(),
        "totals": {
            "targets": len(reports),
            "services": sum(item["counts"]["services"] for item in reports),
            "findings": sum(item["counts"]["findings"] for item in reports),
            "pending_actions": sum(item["counts"]["pending_actions"] for item in reports),
            "completed_actions": sum(item["counts"]["completed_actions"] for item in reports),
            "artifacts": sum(item["counts"]["artifacts"] for item in reports),
        },
        "targets": reports,
    }


@app.get("/api/targets")
def list_targets() -> list[dict[str, Any]]:
    return _list_targets()


@app.post("/api/targets")
def create_target(payload: TargetInput) -> dict[str, Any]:
    ip_address = _validate_ip(payload.resolved_ip())
    target = _new_target(ip_address, payload.label)
    job = _start_enumeration(target["id"]) if payload.start_enumeration else None
    return {
        "ok": True,
        "target": _target_summary(_load_target(target["id"])),
        "job": job,
    }


@app.post("/api/targets/start")
def create_target_and_start(payload: TargetInput) -> dict[str, Any]:
    payload.start_enumeration = True
    return create_target(payload)


@app.get("/api/targets/{target_id}")
def get_target(target_id: str) -> dict[str, Any]:
    target = _load_target(target_id)
    if not _action_is_active(target) and any(item.get("status") == "approved" for item in target.get("agent_actions", [])):
        _dispatch_next_approved_action(target_id)
        return _load_target(target_id)
    return target


@app.delete("/api/targets/{target_id}")
def delete_target(target_id: str) -> dict[str, Any]:
    _delete_target(target_id)
    return {"ok": True, "target_id": target_id}


@app.get("/api/targets/{target_id}/report")
def get_target_report(target_id: str) -> dict[str, Any]:
    return {"ok": True, "report": _target_report(_load_target(target_id))}


@app.get("/api/targets/{target_id}/graph")
def get_target_graph(target_id: str) -> dict[str, Any]:
    target = _load_target(target_id)
    return {
        "ok": True,
        "target_id": target_id,
        "objective_phase": _current_objective_phase(target),
        "attack_graph": target.get("attack_graph", {}),
        "best_path": target.get("best_path"),
        "autonomy": target.get("autonomy", _default_autonomy_state()),
    }


@app.get("/api/targets/{target_id}/journal")
def get_target_journal(target_id: str, limit: int = 40) -> dict[str, Any]:
    target = _load_target(target_id)
    entries = (target.get("decision_journal", []) or [])[-max(1, min(limit, 200)):]
    return {
        "ok": True,
        "target_id": target_id,
        "objective_phase": _current_objective_phase(target),
        "entries": entries,
        "autonomy": target.get("autonomy", _default_autonomy_state()),
    }


@app.get("/api/targets/{target_id}/shell/candidates")
def get_shell_candidates(target_id: str) -> dict[str, Any]:
    target = _load_target(target_id)
    return {
        "ok": True,
        "target_id": target_id,
        "credentials": _credential_hints_from_target(target),
        "candidates": _shell_service_candidates(target),
        "tools": {
            "ssh": bool(shutil.which("ssh")),
            "sshpass": bool(shutil.which("sshpass")),
            "telnet": bool(shutil.which("telnet")),
            "nc": bool(shutil.which("nc") or shutil.which("ncat")),
        },
    }


@app.post("/api/targets/{target_id}/shell/sessions")
def create_shell_session(target_id: str, payload: ShellSessionInput) -> dict[str, Any]:
    session = _create_shell_token(target_id, payload)
    return {
        "ok": True,
        "target_id": target_id,
        "token": session["token"],
        "websocket_path": f"/ws/targets/{target_id}/shell?token={session['token']}",
        "session": {
            "protocol": session["protocol"],
            "host": session["host"],
            "port": session["port"],
            "username": session["username"],
            "label": session["label"],
            "command_display": session["command_display"],
            "warnings": session["warnings"],
        },
    }


@app.post("/api/targets/{target_id}/enumeration/start")
def start_target_enumeration(target_id: str) -> dict[str, Any]:
    job = _start_enumeration(target_id)
    return {"ok": True, "job": job, "target": _target_summary(_load_target(target_id))}


@app.post("/api/targets/{target_id}/initial-recon")
def start_initial_recon(target_id: str) -> dict[str, Any]:
    return start_target_enumeration(target_id)


@app.post("/api/targets/{target_id}/planner/step")
def run_target_planner_step(target_id: str) -> dict[str, Any]:
    _planner_tick_target(target_id)
    return {"ok": True, "target": _load_target(target_id), "planner": _planner_status()}


@app.post("/api/targets/{target_id}/autonomy/profile")
def set_target_autonomy_profile(target_id: str, payload: AutonomyProfileInput) -> dict[str, Any]:
    def mutate(target: dict[str, Any]) -> None:
        target.setdefault("autonomy", _default_autonomy_state())
        target["autonomy"]["profile"] = payload.profile
        target["autonomy"]["pause_reason"] = None
        target["autonomy"]["paused"] = False
        target["autonomy"]["paused_at"] = None
        target["timeline"].append(_timeline_event("autonomy_profile_changed", "Updated autonomy profile.", {"profile": payload.profile}))
        _append_decision_journal(
            target,
            "Autonomy profile changed",
            f"Autonomy profile set to {payload.profile}.",
            kind="autonomy",
            selected_profile=payload.profile,
        )

    target = _with_target_lock(target_id, mutate)
    return {"ok": True, "target": target}


@app.post("/api/targets/{target_id}/autonomy/pause")
def pause_target_autonomy(target_id: str) -> dict[str, Any]:
    def mutate(target: dict[str, Any]) -> None:
        target.setdefault("autonomy", _default_autonomy_state())
        target["autonomy"]["paused"] = True
        target["autonomy"]["pause_reason"] = "Paused by operator."
        target["autonomy"]["paused_at"] = _now()
        target["timeline"].append(_timeline_event("autonomy_paused", "Operator paused autonomy.", {}))
        _append_decision_journal(target, "Autonomy paused", "Operator paused autonomous progression.", kind="autonomy")

    target = _with_target_lock(target_id, mutate)
    return {"ok": True, "target": target}


@app.post("/api/targets/{target_id}/autonomy/resume")
def resume_target_autonomy(target_id: str) -> dict[str, Any]:
    def mutate(target: dict[str, Any]) -> None:
        target.setdefault("autonomy", _default_autonomy_state())
        target["autonomy"]["paused"] = False
        target["autonomy"]["pause_reason"] = None
        target["autonomy"]["paused_at"] = None
        target["timeline"].append(_timeline_event("autonomy_resumed", "Operator resumed autonomy.", {}))
        _append_decision_journal(target, "Autonomy resumed", "Operator resumed autonomous progression.", kind="autonomy")

    target = _with_target_lock(target_id, mutate)
    return {"ok": True, "target": target}


@app.post("/api/targets/{target_id}/actions/{action_id}/approve")
def approve_action(target_id: str, action_id: str, payload: ActionDecisionRequest) -> dict[str, Any]:
    target = _approve_action(target_id, action_id, payload.note)
    return {"ok": True, "target": _target_summary(target), "action_id": action_id}


@app.post("/api/targets/{target_id}/actions/{action_id}/deny")
def deny_action(target_id: str, action_id: str, payload: ActionDecisionRequest) -> dict[str, Any]:
    target = _deny_action(target_id, action_id, payload.note)
    return {"ok": True, "target": _target_summary(target), "action_id": action_id}


@app.delete("/api/targets/{target_id}/actions/{action_id}")
def remove_action(target_id: str, action_id: str, payload: ActionDecisionRequest | None = None) -> dict[str, Any]:
    target = _remove_action(target_id, action_id, payload.note if payload else None)
    return {"ok": True, "target": _target_summary(target), "action_id": action_id}


@app.post("/api/targets/{target_id}/jobs/{job_id}/stop")
def stop_job(target_id: str, job_id: str, payload: ActionDecisionRequest | None = None) -> dict[str, Any]:
    target = _stop_job(target_id, job_id, payload.note if payload else None)
    return {"ok": True, "target": _target_summary(target), "job_id": job_id}


@app.post("/api/targets/{target_id}/actions/{action_id}/stop")
def stop_action(target_id: str, action_id: str, payload: ActionDecisionRequest | None = None) -> dict[str, Any]:
    target = _stop_action(target_id, action_id, payload.note if payload else None)
    return {"ok": True, "target": _target_summary(target), "action_id": action_id}


@app.get("/api/targets/{target_id}/logs")
def get_target_logs(target_id: str, limit: int = 80) -> dict[str, Any]:
    limit = max(1, min(limit, 500))
    log_path = _activity_log_path(target_id)
    if not log_path.exists():
        return {"ok": True, "entries": []}
    lines = log_path.read_text(encoding="utf-8").splitlines()
    entries = [json.loads(line) for line in lines[-limit:]]
    return {"ok": True, "entries": entries}


@app.get("/api/targets/{target_id}/conversation")
def get_target_conversation(target_id: str) -> dict[str, Any]:
    target = _load_target(target_id)
    return {"ok": True, "target_id": target_id, **_conversation_payload(target)}


@app.post("/api/targets/{target_id}/context")
def create_context_block(target_id: str, payload: ContextBlockInput) -> dict[str, Any]:
    created: dict[str, Any] = {}

    def mutate(target: dict[str, Any]) -> None:
        nonlocal created
        created = {
            "id": _new_id("ctx"),
            "title": payload.title.strip(),
            "kind": payload.kind.strip().lower(),
            "content": payload.content.strip(),
            "word_count": _word_count(payload.content),
            "created_at": _now(),
            "updated_at": _now(),
        }
        target.setdefault("context_blocks", []).append(created)
        target["timeline"].append(
            _timeline_event(
                "context_added",
                "Operator attached a new target context block.",
                {"context_block_id": created["id"], "title": created["title"]},
            )
        )

    target = _with_target_lock(target_id, mutate)
    _log_activity(target_id, "context_added", "Saved target context block.", {"context_block_id": created.get("id"), "title": created.get("title")})
    return {"ok": True, "target_id": target_id, "context_block": created, "conversation": _conversation_payload(target)}


@app.delete("/api/targets/{target_id}/context/{context_block_id}")
def delete_context_block(target_id: str, context_block_id: str) -> dict[str, Any]:
    removed: dict[str, Any] | None = None

    def mutate(target: dict[str, Any]) -> None:
        nonlocal removed
        blocks = target.get("context_blocks", [])
        for index, item in enumerate(blocks):
            if item["id"] == context_block_id:
                removed = blocks.pop(index)
                break
        if removed is None:
            raise HTTPException(status_code=404, detail="Context block not found")
        target["timeline"].append(
            _timeline_event(
                "context_removed",
                "Operator removed a saved target context block.",
                {"context_block_id": context_block_id, "title": removed.get("title")},
            )
        )

    target = _with_target_lock(target_id, mutate)
    _log_activity(target_id, "context_removed", "Removed target context block.", {"context_block_id": context_block_id})
    return {"ok": True, "target_id": target_id, "removed": removed, "conversation": _conversation_payload(target)}


@app.post("/api/llm/interact")
def interact_with_target(payload: LlmPromptRequest) -> dict[str, Any]:
    return _build_llm_response(payload)


@app.get("/api/llm/planner")
def get_planner_status() -> dict[str, Any]:
    return {"ok": True, "planner": _planner_status()}


@app.post("/api/llm/planner/start")
def start_planner() -> dict[str, Any]:
    settings = _runtime_settings()
    settings["autoplan_enabled"] = True
    _save_runtime_settings(settings)
    _start_planner_runtime()
    return {"ok": True, "settings": _settings_payload(), "planner": _planner_status()}


@app.post("/api/llm/planner/stop")
def stop_planner() -> dict[str, Any]:
    settings = _runtime_settings()
    settings["autoplan_enabled"] = False
    _save_runtime_settings(settings)
    _stop_planner_runtime()
    return {"ok": True, "settings": _settings_payload(), "planner": _planner_status()}


@app.get("/api/llm/prompts")
def get_llm_prompts(limit: int = 20) -> dict[str, Any]:
    return {"ok": True, "prompts": _llm_prompts_payload(limit)}


@app.get("/api/tools/catalog")
def get_tools_catalog() -> dict[str, Any]:
    return {"ok": True, **_tool_catalog_payload()}


@app.get("/api/diagnostics/ollama")
def ollama_diagnostics() -> dict[str, Any]:
    probe = _probe_ollama()
    return {"ok": probe["reachable"], "ollama": probe}


@app.websocket("/ws/targets/{target_id}/shell")
async def target_shell_websocket(websocket: WebSocket, target_id: str, token: str) -> None:
    await websocket.accept()
    session = _consume_shell_token(token)
    if not session or session.get("target_id") != target_id:
        await websocket.send_text("\r\n[mission-control] Shell token expired or invalid.\r\n")
        await websocket.close(code=4401)
        return

    master_fd, slave_fd = pty.openpty()
    slave_closed = False
    process: subprocess.Popen[bytes] | None = None
    reader_task: asyncio.Task[None] | None = None
    loop = asyncio.get_running_loop()

    async def read_pty() -> None:
        while True:
            try:
                data = await loop.run_in_executor(None, os.read, master_fd, 4096)
            except OSError:
                break
            if not data:
                break
            await websocket.send_text(data.decode("utf-8", errors="replace"))

    try:
        _resize_pty(master_fd, int(session.get("cols") or 100), int(session.get("rows") or 32))
        process = subprocess.Popen(
            session["command"],
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            close_fds=True,
            preexec_fn=os.setsid,
        )
        os.close(slave_fd)
        slave_closed = True
        warnings = "\r\n".join(f"[mission-control] {warning}" for warning in session.get("warnings", []))
        banner = f"[mission-control] attached: {session['command_display']}\r\n"
        if warnings:
            banner += f"{warnings}\r\n"
        await websocket.send_text(banner)
        reader_task = asyncio.create_task(read_pty())

        while True:
            message = await websocket.receive_text()
            try:
                payload = json.loads(message)
            except json.JSONDecodeError:
                payload = {"type": "input", "data": message}
            if payload.get("type") == "resize":
                _resize_pty(master_fd, int(payload.get("cols") or 100), int(payload.get("rows") or 32))
                continue
            if payload.get("type") == "input":
                os.write(master_fd, str(payload.get("data") or "").encode("utf-8", errors="replace"))
    except WebSocketDisconnect:
        pass
    except FileNotFoundError:
        await websocket.send_text(f"\r\n[mission-control] Missing local shell tool: {session['command'][0]}\r\n")
    finally:
        if reader_task:
            reader_task.cancel()
        if not slave_closed:
            try:
                os.close(slave_fd)
            except OSError:
                pass
        try:
            os.close(master_fd)
        except OSError:
            pass
        if process:
            _terminate_shell_process(process)
        _log_activity(target_id, "shell_session_closed", "Interactive shell session closed.", {"protocol": session["protocol"], "host": session["host"], "port": session["port"]})
def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None
