# Root File Notes

This repo has a few historical root-level files from earlier prototype snapshots. This guide helps a maintainer or LLM distinguish active files from retained context.

## Active Entry Points

- `README.md`: project overview and state model.
- `HTB_SETUP.md`: local Mac bring-up.
- `PWNBOX_SETUP.md`: Linux or HTB PwnBox bring-up.
- `API.md`: API endpoint examples.
- `FLOWS.md`: runtime and evidence flow.
- `ROADMAP.md`: implementation status and next work.
- `agent_plan.md`: LLM planner behavior and prompt-analysis guidance.
- `env.example`: non-secret environment defaults.
- `run_dev.sh`: compatibility wrapper for `scripts/run_dev.sh`.
- `htb-codex-up.sh`: remote bootstrap helper for a PwnBox-style host.

## Active Source Directories

- `backend/`: FastAPI backend.
- `frontend/`: React/Vite frontend.
- `scripts/`: supported setup and run scripts.
- `state/`: generated runtime data and evidence.

## Historical Or Misnamed Files

These files are retained for context but are not the current launch path:

- `SKILL.md`, `SKILL (1).md`, `SKILL (2).md`, `SKILL (3).md`: legacy notes for early shell snippets.
- `app.py`, `command_policy.py`, `codex_bridge.py`, `job_runner.py`, `main.py`, `main.jsx`, `util.py`, `__init__.py`: older prototype source fragments at repo root. The active backend is `backend/htbmc/app.py`; the active frontend is `frontend/src/main.jsx`.
- `setup_state_repo.sh`: contains an old JSON schema despite the `.sh` name. Do not execute it as a shell script.
- `git_sync.py`: contains old environment-style configuration despite the `.py` name. Do not import it as Python.
- `agent_decision.schema.json`: currently contains old CSS content rather than a valid decision schema. Do not use it for validation without replacing it.
- `index.html`: older root HTML prototype. The active frontend HTML entry is `frontend/index.html`.

## Analysis Rule

When source and runtime state conflict, use this order:

1. Active code under `backend/` and `frontend/`.
2. Supported scripts under `scripts/`.
3. Generated evidence under `state/`.
4. Historical root-level prototype files only as background context.
