import ipaddress
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import error, request

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(title="HTB Mission Control", version="0.2.0")

LOG_DIR = Path(os.getenv("HTBMC_LOG_DIR", "logs"))
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "htbmc_api.log"

logger = logging.getLogger("htbmc")
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.FileHandler(LOG_FILE)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)

OLLAMA_BASE = os.getenv("HTBMC_OLLAMA_BASE", "http://127.0.0.1:11434")


class TargetSessionRequest(BaseModel):
    ip_address: str = Field(min_length=7, max_length=45)
    label: str | None = Field(default=None, max_length=120)


class LlmPromptRequest(BaseModel):
    ip_address: str = Field(min_length=7, max_length=45)
    prompt: str = Field(min_length=1, max_length=4000)
    model: str = Field(default="llama3.2")


def _validate_ip(ip_address: str) -> str:
    try:
        return str(ipaddress.ip_address(ip_address.strip()))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid IP address") from exc


def _ollama_request(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        f"{OLLAMA_BASE}{path}",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=45) as res:
            return json.loads(res.read().decode("utf-8"))
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        logger.error("ollama_http_error status=%s detail=%s", exc.code, detail)
        raise HTTPException(status_code=502, detail="Ollama HTTP error") from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("ollama_connection_error")
        raise HTTPException(status_code=502, detail="Failed to connect to Ollama") from exc


@app.get("/")
def root() -> dict[str, str]:
    return {"status": "ok", "service": "htb-mission-control"}


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "healthy", "log_file": str(LOG_FILE)}


@app.post("/api/targets/start")
def start_target_session(payload: TargetSessionRequest) -> dict[str, Any]:
    ip_address = _validate_ip(payload.ip_address)
    session_id = f"{ip_address.replace('.', '-')}-{int(datetime.now(tz=timezone.utc).timestamp())}"
    event = {
        "event": "target_session_started",
        "ip_address": ip_address,
        "label": payload.label,
        "session_id": session_id,
        "timestamp_utc": datetime.now(tz=timezone.utc).isoformat(),
    }
    logger.info(json.dumps(event))
    return {
        "ok": True,
        "session": event,
        "next_step": "Submit a prompt to /api/llm/interact for recon guidance.",
    }


@app.post("/api/llm/interact")
def interact_with_target(payload: LlmPromptRequest) -> dict[str, Any]:
    ip_address = _validate_ip(payload.ip_address)
    tools = [
        {
            "name": "run_safe_scan",
            "description": "Run non-intrusive recon commands against a single HTB target.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "target_ip": {"type": "string"},
                    "commands": {"type": "array", "items": {"type": "string"}},
                    "justification": {"type": "string"},
                },
                "required": ["target_ip", "commands"],
            },
        },
        {
            "name": "record_finding",
            "description": "Store an observed service, vulnerability lead, or credential hint.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "target_ip": {"type": "string"},
                    "title": {"type": "string"},
                    "evidence": {"type": "string"},
                    "severity": {"type": "string", "enum": ["low", "medium", "high"]},
                },
                "required": ["target_ip", "title", "evidence"],
            },
        },
    ]

    system_prompt = (
        "You are HTB Mission Control assistant. Return strict JSON with keys: "
        "summary, tool_calls, cautions. tool_calls must only use the provided tool names "
        "and arguments that satisfy each input_schema."
    )

    ollama_payload = {
        "model": payload.model,
        "stream": False,
        "format": "json",
        "prompt": (
            f"{system_prompt}\n"
            f"Target IP: {ip_address}\n"
            f"Tools: {json.dumps(tools)}\n"
            f"User task: {payload.prompt}\n"
        ),
    }

    result = _ollama_request("/api/generate", ollama_payload)
    raw_response = result.get("response", "{}")
    try:
        parsed = json.loads(raw_response)
    except json.JSONDecodeError:
        parsed = {"summary": raw_response, "tool_calls": [], "cautions": ["Non-JSON response from model"]}

    logger.info(
        json.dumps(
            {
                "event": "llm_interaction",
                "ip_address": ip_address,
                "model": payload.model,
                "prompt": payload.prompt,
                "llm_raw_response": raw_response,
                "timestamp_utc": datetime.now(tz=timezone.utc).isoformat(),
            }
        )
    )
    return {
        "ok": True,
        "ip_address": ip_address,
        "tools": tools,
        "llm": parsed,
    }
