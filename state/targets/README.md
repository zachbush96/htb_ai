# Target Case Folders

Each child folder is one target case created by `POST /api/targets` or `POST /api/targets/start`.

Folder names use the backend-generated target ID:

```text
target_<hex>/
```

## Typical Layout

```text
target_<id>/
  target.json
  logs/
    activity.jsonl
  artifacts/
    scans/
    actions/
```

## `target.json`

This is the canonical target record. It is read by:

- `GET /api/targets/<target_id>`
- dashboard, targets, jobs, approvals, conversation, reports, timeline, and loot views

Important arrays:

- `services`: parsed nmap services
- `findings`: generated findings
- `observations`: parsed action or scan observations
- `agent_actions`: recommended, pending, running, completed, failed, denied, or stopped actions
- `jobs`: baseline and follow-up enumeration jobs
- `conversation`: target-scoped LLM messages
- `timeline`: high-level events
- `context_blocks`: operator-saved context snippets

## Analysis Notes

- If the frontend and raw files disagree, trust the raw artifacts first, then `target.json`.
- If `target.json` shows a running PID but no process exists, inspect `jobs` and `agent_actions` status fields, then check `activity.jsonl`.
- Do not edit target state while the backend is running unless you understand the state locks and can restart cleanly.
