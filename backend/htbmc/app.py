import ipaddress
import json
import os
import queue
import re
import shlex
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, model_validator

load_dotenv()
load_dotenv(".htb-codex.env", override=False)

app = FastAPI(title="HTB Mission Control", version="0.4.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

STATE_DIR = Path(os.getenv("HTBMC_STATE_DIR", "./state")).resolve()
TARGETS_DIR = STATE_DIR / "targets"
NMAP_BIN = os.getenv("HTBMC_NMAP_BIN", "nmap")
SCAN_TIMEOUT_SECONDS = int(os.getenv("HTBMC_SCAN_TIMEOUT_SECONDS", "1200"))
ACTION_TIMEOUT_SECONDS = int(os.getenv("HTBMC_ACTION_TIMEOUT_SECONDS", "180"))
OLLAMA_TAILSCALE_HOST = os.getenv("OLLAMA_TAILSCALE_HOST", "").strip()
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "").strip()
OLLAMA_TIMEOUT_SECONDS = float(os.getenv("HTBMC_OLLAMA_TIMEOUT_SECONDS", "5"))
LLM_PROMPTS_LOG_PATH = STATE_DIR / "logs" / "llm_prompts.jsonl"

STATE_LOCK = threading.Lock()
RUNTIME_LOCK = threading.Lock()
EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="htbmc")
EXECUTION_RUNTIME: dict[str, dict[str, Any]] = {}
LIVE_OUTPUT_TAIL_LIMIT = 12000
LIVE_EVENT_LIMIT = 120
PROCESS_STOP_WAIT_SECONDS = 5


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


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def _ensure_dirs() -> None:
    TARGETS_DIR.mkdir(parents=True, exist_ok=True)


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


def _append_jsonl(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(data) + "\n")


def _normalize_target(target: dict[str, Any]) -> dict[str, Any]:
    changed = False
    defaults = {
        "hostnames": [],
        "findings": [],
        "agent_actions": [],
        "observations": [],
        "context_blocks": [],
        "conversation": [],
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
        }.items():
            if key not in action:
                action[key] = value
                changed = True
        if "tool_available" not in action:
            action["tool_available"] = True
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
    }


def _list_targets() -> list[dict[str, Any]]:
    _ensure_dirs()
    targets: list[dict[str, Any]] = []
    for case_dir in TARGETS_DIR.iterdir():
        target_path = case_dir / "target.json"
        if target_path.exists():
            targets.append(_target_summary(_normalize_target(_read_json(target_path))))
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
    candidates = [
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
        "status": status,
        "approval_required": template["approval_required"],
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


def _append_action_templates(target: dict[str, Any], templates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    existing_signatures = {
        _action_signature(item): item
        for item in target.get("agent_actions", [])
        if item.get("status") not in {"denied", "removed", "failed"}
    }
    created: list[dict[str, Any]] = []
    for template in templates:
        signature = f"{template['category']}::{template['command']}"
        if signature in existing_signatures:
            continue
        action = _action_from_template(template)
        target.setdefault("agent_actions", []).append(action)
        existing_signatures[signature] = action
        created.append(action)
    if created:
        target["recommendations"] = _build_recommendations_from_actions(target["agent_actions"]) or _default_recommendations(target["ip_address"])
    return created


def _new_target(ip_address: str, label: str | None) -> dict[str, Any]:
    created_at = _now()
    target_id = _new_id("target")
    display_name = label.strip() if label else f"HTB {ip_address}"
    target = {
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
        "context_blocks": [],
        "conversation": [],
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
    pending_actions = [item for item in target.get("agent_actions", []) if item["status"] in {"pending_approval", "blocked"}]
    observations = target.get("observations", [])
    if not services:
        return "Baseline enumeration finished without open TCP services. Review the proposed wider scan."
    service_list = ", ".join(f"{item['port']}/{item['protocol']} {item['service']}" for item in services[:6])
    summary = f"Baseline enumeration found {len(services)} open services: {service_list}."
    if observations:
        summary += f" Latest observation: {observations[-1]['summary']}"
    if pending_actions:
        summary += f" {len(pending_actions)} action(s) are waiting for approval."
    elif completed_actions:
        summary += f" {len(completed_actions)} approved action(s) have completed."
    return summary


def _action_signature(action: dict[str, Any]) -> str:
    return f"{action['category']}::{action['command']}"


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

    desired = _action_catalog(target, target.get("services", []))
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

    target["recommendations"] = _build_recommendations_from_actions(target["agent_actions"]) or _default_recommendations(target["ip_address"])


def _job_is_active(target: dict[str, Any]) -> bool:
    return any(job["status"] in {"queued", "running", "stopping"} for job in target.get("jobs", []))


def _action_is_active(target: dict[str, Any]) -> bool:
    return any(item["status"] in {"approved", "running", "stopping"} for item in target.get("agent_actions", []))


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
                _refresh_agent_actions(completed_target)
            completed_target["findings"] = _build_findings(completed_target.get("services", []), completed_target.get("observations", []))
            completed_target["latest_summary"] = "Baseline enumeration was stopped by the operator." if stopped else _compose_summary(completed_target)
            completed_target["status"] = "ready" if return_code == 0 or stopped else "error"
            completed_target["phase"] = "awaiting_approval" if stopped else ("enumerated" if return_code == 0 else "enumeration_failed")
            completed_target["timeline"].append(
                _timeline_event(
                    "job_stopped" if stopped else ("job_completed" if return_code == 0 else "job_failed"),
                    "Baseline enumeration was stopped by the operator." if stopped else ("Baseline enumeration finished." if return_code == 0 else "Baseline enumeration failed."),
                    {"job_id": job_id, "return_code": return_code},
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
                missing_target["phase"] = "awaiting_approval"
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
                    break
            if not stopped:
                completed_target["observations"].append(observation)
            _refresh_agent_actions(completed_target)
            completed_target["findings"] = _build_findings(completed_target.get("services", []), completed_target["observations"])
            completed_target["phase"] = "awaiting_approval"
            completed_target["latest_summary"] = "Approved action was stopped by the operator." if stopped else _compose_summary(completed_target)
            completed_target["timeline"].append(
                _timeline_event(
                    "action_stopped" if stopped else ("action_completed" if return_code == 0 else "action_failed"),
                    "Approved agent action was stopped by the operator." if stopped else ("Approved agent action completed." if return_code == 0 else "Approved agent action failed."),
                    {"action_id": action_id, "return_code": return_code},
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
            timeout_target["phase"] = "awaiting_approval"
            timeout_target["latest_summary"] = "Approved action was stopped by the operator." if stopped else "An approved action timed out."
            timeout_target["timeline"].append(
                _timeline_event("action_stopped" if stopped else "action_failed", "Approved action was stopped by the operator." if stopped else "Approved action timed out.", {"action_id": action_id})
            )

        _with_target_lock(target_id, mark_timeout)
        _set_execution_runtime("action", action_id, finished_at=_now(), return_code=None, process=None)
        _log_activity(target_id, "action_stopped" if stopped else "action_failed", "Approved action was stopped." if stopped else "Approved action timed out.", {"action_id": action_id})
    except Exception as exc:  # noqa: BLE001
        def mark_exception(error_target: dict[str, Any]) -> None:
            for action_item in error_target["agent_actions"]:
                if action_item["id"] == action_id:
                    action_item["status"] = "failed"
                    action_item["finished_at"] = _now()
                    action_item["updated_at"] = _now()
                    action_item["error"] = str(exc)
                    break
            error_target["phase"] = "awaiting_approval"
            error_target["latest_summary"] = f"Approved action crashed: {exc}"
            error_target["timeline"].append(
                _timeline_event("action_failed", "Approved action crashed.", {"action_id": action_id, "error": str(exc)})
            )

        _with_target_lock(target_id, mark_exception)
        _log_activity(target_id, "action_failed", "Approved action crashed.", {"action_id": action_id, "error": str(exc)})


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
        target["phase"] = "awaiting_approval"
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
            target["phase"] = "awaiting_approval"
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
    return (
        "You are HTB Mission Control's local red-team assistant. Work like a careful Hack The Box operator. "
        "Use only stored target evidence, keep commands approval-gated, and prefer the smallest evidence-backed next step. "
        "Methodology: 1) confirm coverage of the exposed services, 2) deepen per-service enumeration, 3) test only high-probability anonymous access or default credentials, "
        "4) escalate to focused content discovery such as ffuf or gobuster only after quieter checks, 5) preserve uncertainty and never invent findings. "
        "When you recommend the next step, explain the mindset shift in one sentence and avoid repeating work that target evidence already completed."
    )


def _build_llm_user_prompt(ip_address: str, operator_prompt: str, target_context: str) -> str:
    return f"Target IP: {ip_address}\nOperator request: {operator_prompt}\n\nCurrent target context:\n{target_context}"


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
    normalized = (requested_model or "auto").strip()
    if normalized and normalized not in {"auto", "local-heuristic"}:
        return normalized, probe
    if probe.get("reachable") and probe.get("models"):
        return probe["models"][0], probe
    return None, probe


def _call_ollama_chat(model: str, messages: list[dict[str, str]]) -> dict[str, Any]:
    base_url = _resolved_ollama_base_url()
    if not base_url:
        raise RuntimeError("Ollama is not configured")
    body = json.dumps({"model": model, "messages": messages, "stream": False}).encode("utf-8")
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


def _record_llm_prompt(
    ip_address: str,
    model: str,
    operator_prompt: str,
    target: dict[str, Any] | None,
    target_context: str,
) -> dict[str, Any]:
    entry = {
        "id": _new_id("prompt"),
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

    if active_target is not None:
        def mutate(target: dict[str, Any]) -> None:
            nonlocal queued_actions, user_message
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
            _refresh_agent_actions(target)

        active_target = _with_target_lock(active_target["id"], mutate)

    if resolved_model and active_target is not None:
        try:
            history = _recent_conversation_messages(active_target)
            if history and history[-1]["role"] == "user" and history[-1]["content"] == payload.prompt:
                history = history[:-1]
            response = _call_ollama_chat(
                resolved_model,
                [
                    {"role": "system", "content": _llm_system_prompt()},
                    {"role": "system", "content": f"Current target context:\n{target_context}"},
                    *history,
                    {"role": "user", "content": payload.prompt},
                ],
            )
            assistant_content = response["content"] or ""
            resolved_model = response["model"] or resolved_model
        except Exception as exc:  # noqa: BLE001
            model_error = str(exc)

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
            target["latest_summary"] = _compose_summary(target)
            target["timeline"].append(
                _timeline_event(
                    "conversation_turn",
                    "Operator sent a chat prompt to the mission assistant.",
                    {"prompt_id": prompt_entry["id"], "message_id": assistant_message["id"] if assistant_message else None},
                )
            )

        active_target = _with_target_lock(active_target["id"], append_reply)

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
    return [json.loads(line) for line in lines[-max(1, min(limit, 100)):]]


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
    }



PLANNER_INTERVAL_SECONDS = float(os.getenv("HTBMC_PLANNER_INTERVAL_SECONDS", "20"))
PLANNER_MAX_PENDING_ACTIONS = int(os.getenv("HTBMC_PLANNER_MAX_PENDING_ACTIONS", "6"))
PLANNER_STOP_EVENT = threading.Event()
PLANNER_THREAD: threading.Thread | None = None


def _planner_target_overloaded(target: dict[str, Any]) -> bool:
    pending_count = len([item for item in target.get("agent_actions", []) if item.get("status") in {"pending_approval", "blocked", "approved", "running", "stopping"}])
    return pending_count >= PLANNER_MAX_PENDING_ACTIONS or _job_is_active(target) or _action_is_active(target)


def _planner_eligible_targets() -> list[str]:
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


def _planner_prompt(target: dict[str, Any], context_blob: str) -> str:
    return (
        "Planner mode: propose at most 2 NEXT approval-gated actions based only on stored evidence. "
        "Return strict JSON object with key 'actions' as a list. "
        "Each action supports: label, risk, reason, command, parser, category, stage, priority, mindset. "
        "Do not include already completed actions and do not invent findings.\n\n"
        f"Target: {target.get('display_name') or target['ip_address']}\nContext:\n{context_blob}"
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
    for item in actions[:2]:
        if not isinstance(item, dict):
            continue
        command = str(item.get("command") or "").strip()
        label = str(item.get("label") or "").strip()
        if not command or not label:
            continue
        parsed.append({
            "label": label[:120],
            "risk": str(item.get("risk") or "safe"),
            "approval_required": True,
            "reason": str(item.get("reason") or "Planner suggested the next evidence-backed step."),
            "command": command,
            "parser": str(item.get("parser") or "generic_text"),
            "category": str(item.get("category") or "planner_generated"),
            "stage": str(item.get("stage") or "general"),
            "priority": int(item.get("priority") or 50),
            "mindset": str(item.get("mindset") or "Advance one concrete hypothesis with minimal noise."),
            "source": "planner_runtime",
        })
    return parsed


def _planner_tick_target(target_id: str) -> None:
    target = _load_target(target_id)
    _log_activity(target_id, "planner_tick_started", "Planner tick started.", {"target_id": target_id})
    context_blob, _, _ = _context_snapshot(target, LlmPromptRequest(target_id=target_id, prompt="planner", include_timeline=True))
    model, _ = _resolve_llm_model("auto")
    try:
        queued_actions: list[dict[str, Any]] = []
        if model:
            response = _call_ollama_chat(model, [
                {"role": "system", "content": _llm_system_prompt()},
                {"role": "user", "content": _planner_prompt(target, context_blob)},
            ])
            proposed = _parse_planner_actions(response.get("content", ""))
            if proposed:
                def mutate(locked_target: dict[str, Any]) -> None:
                    nonlocal queued_actions
                    queued_actions = _append_action_templates(locked_target, proposed)
                    if queued_actions:
                        locked_target.setdefault("timeline", []).append(
                            _timeline_event("planner_actions_queued", "Planner queued approval-gated actions.", {"count": len(queued_actions), "action_ids": [a.get("id") for a in queued_actions]})
                        )

                _with_target_lock(target_id, mutate)
        if queued_actions:
            _log_activity(target_id, "planner_actions_queued", "Planner queued actions.", {"count": len(queued_actions), "action_ids": [a.get("id") for a in queued_actions]})
        else:
            _log_activity(target_id, "planner_noop", "Planner found no new actions.", {})
    except Exception as exc:
        _log_activity(target_id, "planner_error", "Planner tick failed.", {"error": str(exc)})


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
    PLANNER_STOP_EVENT.set()
    thread = PLANNER_THREAD
    if thread and thread.is_alive():
        thread.join(timeout=3)


@app.on_event("startup")
def _app_startup() -> None:
    _start_planner_runtime()


@app.on_event("shutdown")
def _app_shutdown() -> None:
    _stop_planner_runtime()

def _settings_payload() -> dict[str, Any]:
    return {
        "state_dir": str(STATE_DIR),
        "targets_dir": str(TARGETS_DIR),
        "nmap_bin": NMAP_BIN,
        "nmap_path": shutil.which(NMAP_BIN),
        "scan_timeout_seconds": SCAN_TIMEOUT_SECONDS,
        "action_timeout_seconds": ACTION_TIMEOUT_SECONDS,
        "ollama_base_url": _resolved_ollama_base_url(),
        "ollama_timeout_seconds": OLLAMA_TIMEOUT_SECONDS,
        "cors": {"allow_origins": ["*"], "allow_credentials": False},
    }


def _resolved_ollama_base_url() -> str | None:
    if OLLAMA_BASE_URL:
        return OLLAMA_BASE_URL.rstrip("/")
    if OLLAMA_TAILSCALE_HOST:
        return f"http://{OLLAMA_TAILSCALE_HOST}:11434"
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
    return _load_target(target_id)


@app.delete("/api/targets/{target_id}")
def delete_target(target_id: str) -> dict[str, Any]:
    _delete_target(target_id)
    return {"ok": True, "target_id": target_id}


@app.get("/api/targets/{target_id}/report")
def get_target_report(target_id: str) -> dict[str, Any]:
    return {"ok": True, "report": _target_report(_load_target(target_id))}


@app.post("/api/targets/{target_id}/enumeration/start")
def start_target_enumeration(target_id: str) -> dict[str, Any]:
    job = _start_enumeration(target_id)
    return {"ok": True, "job": job, "target": _target_summary(_load_target(target_id))}


@app.post("/api/targets/{target_id}/initial-recon")
def start_initial_recon(target_id: str) -> dict[str, Any]:
    return start_target_enumeration(target_id)


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


@app.get("/api/llm/prompts")
def get_llm_prompts(limit: int = 20) -> dict[str, Any]:
    return {"ok": True, "prompts": _llm_prompts_payload(limit)}


@app.get("/api/diagnostics/ollama")
def ollama_diagnostics() -> dict[str, Any]:
    probe = _probe_ollama()
    return {"ok": probe["reachable"], "ollama": probe}
def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None
