# Mission Control Flows

This file explains how the project moves data from an operator action to persistent evidence. Use it when reconstructing a run or asking an LLM to reason from project files.

## 1. Local Startup

Primary files:

- `scripts/bootstrap.sh`
- `scripts/run_dev.sh`
- `scripts/run_frontend.sh`
- `backend/htbmc/app.py`
- `frontend/src/main.jsx`

Flow:

1. `scripts/bootstrap.sh` copies `env.example` to `.env` if needed, selects Python `3.11` through `3.13`, creates `.venv`, installs `backend/requirements.txt`, and runs `npm install` in `frontend/`.
2. `scripts/run_dev.sh` activates `.venv`, exports `PYTHONPATH="$ROOT/backend"`, and starts `uvicorn htbmc.app:app`.
3. `scripts/run_frontend.sh` starts Vite from `frontend/`.
4. `backend/htbmc/app.py` loads `.env`, then `.htb-codex.env`, then resolves `STATE_DIR`.

Example:

```bash
./scripts/bootstrap.sh
./scripts/run_dev.sh
./scripts/run_frontend.sh
```

## 2. Target Creation And Enumeration

Primary backend functions:

- `create_target()` in `backend/htbmc/app.py`
- `create_target_and_start()` in `backend/htbmc/app.py`
- `_new_target()`
- `_start_enumeration()`
- `_run_enumeration_job()`
- `_build_nmap_command()`
- `_parse_nmap_xml()`

Flow:

1. The operator posts to `POST /api/targets` or `POST /api/targets/start`.
2. `_new_target()` creates `state/targets/<target_id>/target.json`.
3. `_log_activity()` appends a target-created event to `state/targets/<target_id>/logs/activity.jsonl`.
4. `_start_enumeration()` queues a baseline nmap job.
5. `_build_nmap_command()` writes scan outputs under `state/targets/<target_id>/artifacts/scans/`.
6. `_parse_nmap_xml()` extracts services and hostnames back into `target.json`.
7. `_build_findings()` and `_refresh_agent_actions()` derive findings and next recommended actions.

Example:

```bash
curl -s -X POST http://127.0.0.1:8000/api/targets/start \
  -H 'Content-Type: application/json' \
  -d '{"ip_address":"10.129.31.195","label":"htb target"}'
```

## 3. Approval-Gated Actions

Primary backend functions:

- `_action_catalog()`
- `_append_action_templates()`
- `_approve_action()`
- `_deny_action()`
- `_run_agent_action()`
- `_stop_action()`
- `_remove_action()`

Flow:

1. Recommended actions are stored in the `agent_actions` array in `target.json`.
2. Safe allowlisted commands may be auto-approved by `_auto_approve_allowlisted_actions()`.
3. Approval-required commands stay queued until the operator approves or denies them.
4. `_run_agent_action()` writes raw command output to `state/targets/<target_id>/artifacts/actions/<action_id>.log`.
5. `_parse_action_output()` turns useful output into observations or findings.
6. `target.json` receives status, PID, return code, output path, summary, and live tail fields.

Example:

```bash
curl -s -X POST http://127.0.0.1:8000/api/targets/<target_id>/actions/<action_id>/approve \
  -H 'Content-Type: application/json' \
  -d '{"note":"approved after reviewing target scope"}'
```

## 4. LLM Conversation

Primary backend functions:

- `_build_llm_response()`
- `_record_llm_prompt()`
- `_record_llm_response()`
- `_context_snapshot()`
- `_llm_trace_payload()`

Flow:

1. The frontend posts an operator prompt to `POST /api/llm/interact`.
2. `_context_snapshot()` selects target evidence from services, findings, observations, pending actions, timeline, execution history, and selected context blocks.
3. `_record_llm_prompt()` appends the full system prompt, user prompt, operator prompt, target ID, and model to `state/logs/llm_prompts.jsonl`.
4. The backend calls Ollama if configured, otherwise it returns a fallback response.
5. `_record_llm_response()` appends the paired response event to `state/logs/llm_prompts.jsonl`.
6. The target conversation and timeline are updated in `target.json`.

Example:

```bash
curl -s -X POST http://127.0.0.1:8000/api/llm/interact \
  -H 'Content-Type: application/json' \
  -d '{"target_id":"<target_id>","prompt":"What is the next smallest useful step?","model":"auto"}'
```

## 5. Autonomous Planner

Primary backend functions:

- `_run_planner_step()`
- `_llm_agent_worker()`
- `_planner_context_signature()`
- `_recent_planner_events()`

Flow:

1. Planner settings are read from `state/settings/runtime.json`.
2. `POST /api/targets/<target_id>/planner/step` runs one planner turn.
3. `POST /api/llm/planner/start` enables the background worker.
4. `_run_planner_step()` skips active targets and unchanged contexts to avoid noisy repeats.
5. Planner runs and skips are appended to `state/logs/llm_planner.jsonl`.
6. Queued LLM-proposed action IDs are written back to `target.json`.

Example:

```bash
curl -s -X POST http://127.0.0.1:8000/api/targets/<target_id>/planner/step
curl -s http://127.0.0.1:8000/api/llm/trace?target_id=<target_id>
```

## 6. Reporting And Review

Primary backend functions:

- `_target_report()`
- `reports_overview()`
- `get_target_report()`

Flow:

1. `GET /api/targets/<target_id>/report` returns a target-scoped report payload.
2. `_target_report()` includes counts, services, findings, observations, actions, artifacts, and conversation metadata.
3. `GET /api/reports/overview` summarizes all target reports.
4. The frontend report and loot views render this data without needing to parse raw files directly.

For analysis, prefer `target.json` plus `artifacts/` when validating claims, then use the report endpoint as a summarized view.
