from pathlib import Path
from typing import Any

from ..config import settings
from ..storage.json_store import read_json, write_json


def target_dir(target_id: str) -> Path:
    return settings.TARGETS_DIR / target_id


def target_file(target_id: str) -> Path:
    return target_dir(target_id) / "target.json"


def load_target(target_id: str) -> dict[str, Any]:
    return read_json(target_file(target_id))


def save_target(target: dict[str, Any]) -> dict[str, Any]:
    write_json(target_file(target["id"]), target)
    return target
