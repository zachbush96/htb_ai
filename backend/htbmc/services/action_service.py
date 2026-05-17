from typing import Any


def next_pending_actions(target: dict[str, Any]) -> list[dict[str, Any]]:
    return [a for a in target.get("agent_actions", []) if a.get("status") == "pending_approval"]


def mark_action(target: dict[str, Any], action_id: str, status: str, note: str | None = None) -> dict[str, Any]:
    for action in target.get("agent_actions", []):
        if action.get("id") == action_id:
            action["status"] = status
            if note:
                action["note"] = note
            return action
    raise KeyError(action_id)
