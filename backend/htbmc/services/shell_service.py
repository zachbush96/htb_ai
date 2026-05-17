import time
import uuid
from typing import Any


def new_session_token(ttl_seconds: int) -> dict[str, Any]:
    now = time.time()
    return {
        "token": uuid.uuid4().hex,
        "created_at_epoch": now,
        "expires_at_epoch": now + ttl_seconds,
    }


def token_expired(session: dict[str, Any], now_epoch: float | None = None) -> bool:
    now = now_epoch if now_epoch is not None else time.time()
    return now > float(session.get("expires_at_epoch", 0))
