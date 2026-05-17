import json
import urllib.request
from typing import Any


def build_prompt(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2)


def ollama_request(base_url: str, timeout_seconds: float, body: dict[str, Any]) -> dict[str, Any]:
    req = urllib.request.Request(
        url=f"{base_url.rstrip('/')}/api/chat",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
        return json.loads(resp.read().decode("utf-8"))
