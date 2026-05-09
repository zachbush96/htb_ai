import ipaddress
import json
import os
import re
import shlex
import shutil
import subprocess
import threading
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

app = FastAPI(title="HTB Mission Control", version="0.3.0")
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
OLLAMA_TAILSCALE_HOST = os.getenv("OLLAMA_TAILSCALE_HOST", "").strip()
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "").strip()
OLLAMA_TIMEOUT_SECONDS = float(os.getenv("HTBMC_OLLAMA_TIMEOUT_SECONDS", "5"))

STATE_LOCK = threading.Lock()
EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="htbmc")


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
    ip_address: str = Field(min_length=7, max_length=45)
    prompt: str = Field(min_length=1, max_length=4000)
    model: str = Field(default="local-heuristic", max_length=120)


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


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp_path.replace(path)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_target(target_id: str) -> dict[str, Any]:
    path = _target_file(target_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Target not found")
    return _read_json(path)


def _save_target(target: dict[str, Any]) -> dict[str, Any]:
    target["updated_at"] = _now()
    _write_json(_target_file(target["id"]), target)
    return target


def _with_target_lock(target_id: str, mutator) -> dict[str, Any]:
    with STATE_LOCK:
        target = _load_target(target_id)
        mutator(target)
        return _save_target(target)


def _timeline_event(event_type: str, message: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "id": _new_id("evt"),
        "type": event_type,
        "message": message,
        "data": data or {},
        "timestamp_utc": _now(),
    }


def _target_summary(target: dict[str, Any]) -> dict[str, Any]:
    latest_job = target["jobs"][-1] if target["jobs"] else None
    services = target.get("services", [])
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
    }


def _list_targets() -> list[dict[str, Any]]:
    _ensure_dirs()
    targets: list[dict[str, Any]] = []
    for case_dir in TARGETS_DIR.iterdir():
        target_path = case_dir / "target.json"
        if target_path.exists():
            targets.append(_target_summary(_read_json(target_path)))
    targets.sort(key=lambda item: item["updated_at"], reverse=True)
    return targets


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
        "findings": [],
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
    return target


def _default_recommendations(ip_address: str) -> list[dict[str, Any]]:
    return [
        {
            "id": _new_id("rec"),
            "label": "Run the baseline safe scan",
            "risk": "safe",
            "why": "Start with service discovery before choosing protocol-specific tooling.",
            "command": f"{NMAP_BIN} -Pn -T4 --top-ports 1000 -sV --version-light {ip_address}",
        }
    ]


def _build_nmap_command(target: dict[str, Any], job_id: str) -> tuple[list[str], Path, Path]:
    scans_dir = _target_dir(target["id"]) / "artifacts" / "scans"
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


def _build_findings(target: dict[str, Any], services: list[dict[str, Any]]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for service in services:
        findings.append(
            {
                "id": _new_id("finding"),
                "title": f"Open {service['service']} service on {service['port']}/{service['protocol']}",
                "severity": _service_severity(service["service"], service["port"]),
                "evidence": f"Initial nmap enumeration identified {service['service']} on port {service['port']}.",
                "confidence": "observed",
                "port": service["port"],
            }
        )
    if not services:
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


def _build_recommendations(target: dict[str, Any]) -> list[dict[str, Any]]:
    ip_address = target["ip_address"]
    recommendations: list[dict[str, Any]] = []
    services = target.get("services", [])

    if not services:
        recommendations.append(
            {
                "id": _new_id("rec"),
                "label": "Widen enumeration coverage",
                "risk": "safe",
                "why": "No open TCP ports appeared in the default scan. A full port sweep is the next low-risk move.",
                "command": f"{NMAP_BIN} -Pn -p- --min-rate 2000 {ip_address}",
            }
        )
        return recommendations

    seen_web = False
    seen_smb = False
    seen_ftp = False
    seen_dns = False
    for service in services:
        service_name = (service["service"] or "").lower()
        port = service["port"]
        tunnel = (service.get("tunnel") or "").lower()
        is_web = service_name in {"http", "http-proxy", "https"} or tunnel == "ssl" or port in {80, 443, 8080, 8443}
        if is_web and not seen_web:
            scheme = "https" if service_name == "https" or tunnel == "ssl" or port in {443, 8443} else "http"
            base_url = f"{scheme}://{ip_address}:{port}" if port not in {80, 443} else f"{scheme}://{ip_address}"
            recommendations.append(
                {
                    "id": _new_id("rec"),
                    "label": f"Fingerprint the web surface on {port}",
                    "risk": "safe",
                    "why": "HTTP service found. Identify framework, headers, and likely content paths before fuzzing deeper.",
                    "command": f"whatweb {base_url} && curl -isk {base_url}",
                }
            )
            recommendations.append(
                {
                    "id": _new_id("rec"),
                    "label": f"Enumerate directories on {port}",
                    "risk": "safe",
                    "why": "Content discovery is usually the highest-value next step once a web port is confirmed.",
                    "command": f"feroxbuster -u {base_url} -k -x php,txt,html,aspx,jsp",
                }
            )
            seen_web = True
        if port in {139, 445} and not seen_smb:
            recommendations.append(
                {
                    "id": _new_id("rec"),
                    "label": "Check anonymous SMB access",
                    "risk": "safe",
                    "why": "Anonymous share enumeration is common and low-risk on SMB targets.",
                    "command": f"smbclient -N -L //{ip_address}",
                }
            )
            recommendations.append(
                {
                    "id": _new_id("rec"),
                    "label": "Run SMB-focused enumeration",
                    "risk": "safe",
                    "why": "SMB metadata often reveals usernames, shares, and host role information.",
                    "command": f"enum4linux-ng -A {ip_address}",
                }
            )
            seen_smb = True
        if port == 21 and not seen_ftp:
            recommendations.append(
                {
                    "id": _new_id("rec"),
                    "label": "Test anonymous FTP access",
                    "risk": "safe",
                    "why": "Anonymous FTP remains a fast check with low risk and high payoff.",
                    "command": f"printf 'user anonymous anonymous\\nls\\nquit\\n' | ftp -inv {ip_address}",
                }
            )
            seen_ftp = True
        if port == 53 and not seen_dns:
            recommendations.append(
                {
                    "id": _new_id("rec"),
                    "label": "Attempt a DNS zone transfer check",
                    "risk": "safe",
                    "why": "If the target runs DNS, zone transfer testing is a compact next step.",
                    "command": f"dig axfr @{ip_address}",
                }
            )
            seen_dns = True
        if port == 22:
            recommendations.append(
                {
                    "id": _new_id("rec"),
                    "label": "Preserve SSH as an access path",
                    "risk": "informational",
                    "why": "SSH is available. Prioritize credential and key discovery on other surfaces before login attempts.",
                    "command": "Wait for usernames, passwords, or keys before attempting authentication.",
                }
            )
        if port in {5985, 5986}:
            recommendations.append(
                {
                    "id": _new_id("rec"),
                    "label": "Treat WinRM as a post-credential path",
                    "risk": "informational",
                    "why": "WinRM is open. Keep it in reserve until valid Windows credentials are found.",
                    "command": "Queue Evil-WinRM only after credential discovery.",
                }
            )

    return recommendations or _default_recommendations(ip_address)


def _compose_summary(target: dict[str, Any]) -> str:
    services = target.get("services", [])
    if not services:
        return "Baseline enumeration finished without open TCP services. The next sensible move is a wider scan."
    service_list = ", ".join(f"{item['port']}/{item['protocol']} {item['service']}" for item in services[:6])
    extra = "" if len(services) <= 6 else f" and {len(services) - 6} more"
    return f"Baseline enumeration found {len(services)} open services: {service_list}{extra}."


def _job_is_active(target: dict[str, Any]) -> bool:
    return any(job["status"] in {"queued", "running"} for job in target.get("jobs", []))


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
        }
        target["jobs"].append(job)
        target["status"] = "enumerating"
        target["phase"] = "initial_enumeration"
        target["latest_summary"] = "Baseline enumeration queued. Waiting for scan results."
        target["timeline"].append(
            _timeline_event("job_queued", "Queued the baseline enumeration scan.", {"job_id": job_id})
        )
        _save_target(target)

    EXECUTOR.submit(_run_enumeration_job, target_id, job_id)
    return job


def _run_enumeration_job(target_id: str, job_id: str) -> None:
    def mark_running(target: dict[str, Any]) -> None:
        for job in target["jobs"]:
            if job["id"] == job_id:
                job["status"] = "running"
                job["started_at"] = _now()
                job["updated_at"] = _now()
                break
        target["latest_summary"] = "Baseline enumeration is running."
        target["timeline"].append(
            _timeline_event("job_started", "Initial enumeration scan is running.", {"job_id": job_id})
        )

    _with_target_lock(target_id, mark_running)

    with STATE_LOCK:
        target = _load_target(target_id)
        job = next(item for item in target["jobs"] if item["id"] == job_id)
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
        return

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=SCAN_TIMEOUT_SECONDS,
            check=False,
        )
        combined_output = result.stdout
        if result.stderr:
            combined_output = f"{combined_output}\n\n[stderr]\n{result.stderr}".strip()
        text_path.write_text(combined_output, encoding="utf-8", errors="replace")
        services, hostnames = _parse_nmap_xml(xml_path)

        def mark_complete(completed_target: dict[str, Any]) -> None:
            for completed_job in completed_target["jobs"]:
                if completed_job["id"] == job_id:
                    completed_job["status"] = "completed" if result.returncode == 0 else "failed"
                    completed_job["finished_at"] = _now()
                    completed_job["updated_at"] = _now()
                    completed_job["return_code"] = result.returncode
                    completed_job["summary"] = (
                        f"Parsed {len(services)} open services from the baseline scan."
                        if result.returncode == 0
                        else "nmap exited with a non-zero status."
                    )
                    completed_job["error"] = None if result.returncode == 0 else combined_output[-800:]
                    break
            completed_target["services"] = services
            completed_target["hostnames"] = hostnames
            completed_target["findings"] = _build_findings(completed_target, services)
            completed_target["recommendations"] = _build_recommendations(completed_target)
            completed_target["latest_summary"] = _compose_summary(completed_target)
            completed_target["status"] = "ready" if result.returncode == 0 else "error"
            completed_target["phase"] = "enumerated" if result.returncode == 0 else "enumeration_failed"
            completed_target["timeline"].append(
                _timeline_event(
                    "job_completed" if result.returncode == 0 else "job_failed",
                    "Baseline enumeration finished." if result.returncode == 0 else "Baseline enumeration failed.",
                    {"job_id": job_id, "return_code": result.returncode},
                )
            )

        _with_target_lock(target_id, mark_complete)
    except subprocess.TimeoutExpired:
        def mark_timeout(timeout_target: dict[str, Any]) -> None:
            for timeout_job in timeout_target["jobs"]:
                if timeout_job["id"] == job_id:
                    timeout_job["status"] = "failed"
                    timeout_job["finished_at"] = _now()
                    timeout_job["updated_at"] = _now()
                    timeout_job["error"] = "Enumeration timed out"
                    break
            timeout_target["status"] = "error"
            timeout_target["phase"] = "enumeration_failed"
            timeout_target["latest_summary"] = "Baseline enumeration timed out before completing."
            timeout_target["timeline"].append(
                _timeline_event("job_failed", "Baseline enumeration timed out.", {"job_id": job_id})
            )

        _with_target_lock(target_id, mark_timeout)
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


def _generic_prompt_recommendations(ip_address: str) -> list[dict[str, Any]]:
    dummy_target = {"ip_address": ip_address, "services": []}
    return _build_recommendations(dummy_target)


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


@app.post("/api/targets/{target_id}/enumeration/start")
def start_target_enumeration(target_id: str) -> dict[str, Any]:
    job = _start_enumeration(target_id)
    return {"ok": True, "job": job, "target": _target_summary(_load_target(target_id))}


@app.post("/api/targets/{target_id}/initial-recon")
def start_initial_recon(target_id: str) -> dict[str, Any]:
    return start_target_enumeration(target_id)


@app.post("/api/llm/interact")
def interact_with_target(payload: LlmPromptRequest) -> dict[str, Any]:
    ip_address = _validate_ip(payload.ip_address.strip())
    matched_target = None
    for target_summary in _list_targets():
        if target_summary["ip_address"] == ip_address:
            matched_target = _load_target(target_summary["id"])
            break

    if matched_target is None:
        recommendations = _generic_prompt_recommendations(ip_address)
        summary = "No stored target context yet. Start baseline enumeration first."
    else:
        recommendations = matched_target.get("recommendations", [])
        summary = matched_target.get("latest_summary", "")

    return {
        "ok": True,
        "ip_address": ip_address,
        "llm": {
            "summary": summary,
            "tool_calls": recommendations,
            "cautions": [
                "This response is heuristic. Review commands against current target evidence before executing them."
            ],
        },
    }


@app.get("/api/diagnostics/ollama")
def ollama_diagnostics() -> dict[str, Any]:
    probe = _probe_ollama()
    return {"ok": probe["reachable"], "ollama": probe}
