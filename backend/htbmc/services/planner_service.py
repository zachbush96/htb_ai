from typing import Any


def should_tick(runtime_settings: dict[str, Any], pending_actions: int) -> bool:
    if not runtime_settings.get("autoplan_enabled"):
        return False
    return pending_actions < int(runtime_settings.get("autoplan_max_actions_per_turn", 4))
