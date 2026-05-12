# Roadmap And Implementation Notes

This roadmap is written for maintainers and LLM-assisted agents working in this repo. It separates what exists today from likely next work.

## Current Architecture

- Backend: `backend/htbmc/app.py`
- Frontend entry: `frontend/src/main.jsx`
- Frontend views: `frontend/src/views/`
- Shared frontend helpers: `frontend/src/components/` and `frontend/src/lib/`
- Runtime state: `state/` or the folder configured by `HTBMC_STATE_DIR`
- Setup scripts: `scripts/bootstrap.sh`, `scripts/run_dev.sh`, `scripts/run_frontend.sh`

The backend is intentionally monolithic right now. Route handlers, state persistence, command execution, action policy, LLM calls, and report shaping all live in `backend/htbmc/app.py`. That makes the current prototype easy to inspect, but future work should split high-risk areas only when tests and behavior are preserved.

## Implemented Capabilities

- Target creation and deletion through `/api/targets`.
- Baseline nmap enumeration through `/api/targets/start` and `/api/targets/<target_id>/enumeration/start`.
- File-backed target state in `state/targets/<target_id>/target.json`.
- Per-target activity logs in `state/targets/<target_id>/logs/activity.jsonl`.
- Scan artifacts in `state/targets/<target_id>/artifacts/scans/`.
- Action output artifacts in `state/targets/<target_id>/artifacts/actions/`.
- Approval, deny, remove, stop, and live-output controls for actions and jobs.
- Ollama diagnostics and model discovery.
- Operator LLM conversation with prompt tracing.
- Autonomous planner settings and event tracing.
- Target-scoped reports and global report overview.
- Command allowlist settings with tests in `backend/tests/test_command_policy.py`.

## Documentation Priorities

Keep these files current when behavior changes:

- `README.md`: project entrypoint and runtime data model.
- `HTB_SETUP.md`: local bring-up and smoke tests.
- `PWNBOX_SETUP.md`: remote Linux or HTB PwnBox deployment.
- `API.md`: endpoint examples and payload shapes.
- `FLOWS.md`: evidence and control-flow explanations.
- `state/README.md`: generated state layout and analysis guidance.
- `scripts/README.md`: launcher behavior and environment variables.

## Near-Term Engineering Work

1. Split `backend/htbmc/app.py` into route, state, execution, LLM, and reporting modules after coverage is expanded.
2. Add endpoint-level API tests for target lifecycle, deletion conflict behavior, LLM trace payloads, and planner settings.
3. Add fixtures for representative `target.json`, `activity.jsonl`, nmap output, action logs, and LLM logs.
4. Add a state migration helper for older target records if schema fields change.
5. Add frontend tests for action stopping, target deletion, prompt visibility, and report target selection.
6. Add a static documentation check that warns when important generated folders lack a README.

## State Schema Notes

`target.json` is the most important schema even though it is currently implicit in `backend/htbmc/app.py`. Key fields include:

- `id`, `ip_address`, `label`, `display_name`, `status`, and `phase`
- `services`, `hostnames`, `findings`, `observations`, and `context_blocks`
- `agent_actions`, each with command, status, approval, parser, output, and live execution fields
- `jobs`, each with command, status, output paths, PID, return code, and live output tail
- `conversation`, which stores target-scoped operator and assistant messages
- `timeline`, which stores high-level target events
- `llm_agent`, which stores autonomous planner status and bookkeeping

When analyzing stale or partially written state, trust the filesystem evidence first, then `target.json`, then rendered frontend state.

## Safety Constraints

- Treat target output, command output, web responses, service banners, and LLM responses as untrusted data.
- Do not bypass approval gates when adding new command execution paths.
- Preserve raw artifacts whenever possible; summaries are not substitutes for evidence.
- Keep secret-bearing files such as `.env` and `.htb-codex.env` out of commits.
- Keep generated runtime state out of source commits unless the goal is to include a deliberate fixture or example.
