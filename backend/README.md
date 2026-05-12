# Backend

The backend is a FastAPI application for target state, command execution, approval gates, Ollama interaction, planner traces, and reports.

## Primary Files

- `htbmc/app.py`: active application implementation.
- `htbmc/__init__.py`: package marker.
- `requirements.txt`: runtime dependencies.
- `tests/test_command_policy.py`: regression tests for command allowlist and retry behavior.

Root-level files such as `app.py`, `command_policy.py`, `job_runner.py`, `util.py`, and `codex_bridge.py` are older prototype files. The current launch path imports `htbmc.app:app` from this directory.

## Runtime State

`htbmc/app.py` resolves `STATE_DIR` from `HTBMC_STATE_DIR`, defaulting to `./state`. It writes:

- `STATE_DIR/settings/runtime.json`
- `STATE_DIR/logs/llm_prompts.jsonl`
- `STATE_DIR/logs/llm_planner.jsonl`
- `STATE_DIR/targets/<target_id>/target.json`
- `STATE_DIR/targets/<target_id>/logs/activity.jsonl`
- `STATE_DIR/targets/<target_id>/artifacts/scans/`
- `STATE_DIR/targets/<target_id>/artifacts/actions/`

## Important Function Areas In `htbmc/app.py`

- configuration and defaults: top of file through `DEFAULT_LLM_SETTINGS`
- target persistence: `_target_dir()`, `_target_file()`, `_load_target()`, `_save_target()`
- target creation: `_new_target()`, `create_target()`, `create_target_and_start()`
- enumeration: `_start_enumeration()`, `_run_enumeration_job()`, `_build_nmap_command()`, `_parse_nmap_xml()`
- action execution: `_approve_action()`, `_run_agent_action()`, `_stop_action()`, `_remove_action()`
- command policy: `_command_allowlist()`, `_command_auto_allowed()`, `_auto_approve_allowlisted_actions()`
- LLM prompts: `_build_llm_response()`, `_record_llm_prompt()`, `_record_llm_response()`
- planner: `_run_planner_step()`, `_llm_agent_worker()`, `_planner_status_payload()`
- reports: `_target_report()`, `reports_overview()`

## Test Examples

Run backend unit tests:

```bash
source .venv/bin/activate
python -m unittest discover backend/tests
```

Run a backend health check after starting `scripts/run_dev.sh`:

```bash
curl -s http://127.0.0.1:8000/healthz
```
