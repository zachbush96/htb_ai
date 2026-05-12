# API Quick Reference

Base URL: `http://127.0.0.1:8000`

## Verified endpoints

The following paths were exercised successfully during the May 10, 2026 local bring-up:

```bash
curl -s http://127.0.0.1:8000/
curl -s http://127.0.0.1:8000/healthz
curl -s http://127.0.0.1:8000/api/settings
curl -s http://127.0.0.1:8000/api/diagnostics/ollama
curl -s http://127.0.0.1:8000/api/targets
```

## Health and runtime

```bash
curl -s http://127.0.0.1:8000/
curl -s http://127.0.0.1:8000/healthz
curl -s http://127.0.0.1:8000/api/settings
curl -s http://127.0.0.1:8000/api/diagnostics/ollama
curl -s http://127.0.0.1:8000/api/reports/overview
```

`/healthz` includes the resolved `state_dir`, Ollama status, and basic runtime flags. Use it first when an LLM or operator needs to confirm which `state/` tree the backend is reading.

`/api/settings` returns runtime settings from `state/settings/runtime.json`, including LLM usage, planner behavior, and command policy. The backend merges missing values from defaults in `backend/htbmc/app.py`.

## Targets

List targets:

```bash
curl -s http://127.0.0.1:8000/api/targets
```

Create a target without starting enumeration:

```bash
curl -s -X POST http://127.0.0.1:8000/api/targets \
  -H 'Content-Type: application/json' \
  -d '{"ip_address":"10.129.31.195","label":"target name","start_enumeration":false}'
```

Create a target and immediately queue baseline enumeration:

```bash
curl -s -X POST http://127.0.0.1:8000/api/targets/start \
  -H 'Content-Type: application/json' \
  -d '{"ip_address":"10.129.31.195","label":"target name"}'
```

Inspect a target:

```bash
curl -s http://127.0.0.1:8000/api/targets/<target_id>
curl -s http://127.0.0.1:8000/api/targets/<target_id>/report
curl -s 'http://127.0.0.1:8000/api/targets/<target_id>/logs?limit=80'
curl -s http://127.0.0.1:8000/api/targets/<target_id>/conversation
```

Restart enumeration:

```bash
curl -s -X POST http://127.0.0.1:8000/api/targets/<target_id>/enumeration/start
curl -s -X POST http://127.0.0.1:8000/api/targets/<target_id>/initial-recon
```

Delete a target:

```bash
curl -s -X DELETE http://127.0.0.1:8000/api/targets/<target_id>
```

If deletion returns HTTP `409`, the target still has a running job or action. Stop it first or wait for completion.

State written by these endpoints:

- `state/targets/<target_id>/target.json`: canonical target record.
- `state/targets/<target_id>/logs/activity.jsonl`: target activity events.
- `state/targets/<target_id>/artifacts/scans/`: nmap `.nmap` and `.xml` outputs.

## Action approvals

Approve an action:

```bash
curl -s -X POST http://127.0.0.1:8000/api/targets/<target_id>/actions/<action_id>/approve \
  -H 'Content-Type: application/json' \
  -d '{"note":"approved from curl"}'
```

Deny an action:

```bash
curl -s -X POST http://127.0.0.1:8000/api/targets/<target_id>/actions/<action_id>/deny \
  -H 'Content-Type: application/json' \
  -d '{"note":"denied from curl"}'
```

Remove an action card:

```bash
curl -s -X DELETE http://127.0.0.1:8000/api/targets/<target_id>/actions/<action_id> \
  -H 'Content-Type: application/json' \
  -d '{"note":"removed from curl"}'
```

## Execution control

Stop a running execution:

```bash
curl -s -X POST http://127.0.0.1:8000/api/targets/<target_id>/jobs/<job_id>/stop \
  -H 'Content-Type: application/json' \
  -d '{"note":"stop requested from curl"}'

curl -s -X POST http://127.0.0.1:8000/api/targets/<target_id>/actions/<action_id>/stop \
  -H 'Content-Type: application/json' \
  -d '{"note":"stop requested from curl"}'
```

Execution metadata is written back into the matching job or action entry in `target.json`. Raw command output is also retained:

- jobs: `state/targets/<target_id>/artifacts/scans/`
- actions: `state/targets/<target_id>/artifacts/actions/<action_id>.log`

The frontend uses `live_output_tail`, `pid`, `return_code`, `output_bytes`, `stop_requested_at`, and `termination_reason` fields from `target.json` to explain what is happening while a command runs.

## Target context blocks

Add a saved note:

```bash
curl -s -X POST http://127.0.0.1:8000/api/targets/<target_id>/context \
  -H 'Content-Type: application/json' \
  -d '{"title":"Operator note","kind":"notes","content":"Credential source or exploitation note."}'
```

Delete a saved note:

```bash
curl -s -X DELETE http://127.0.0.1:8000/api/targets/<target_id>/context/<context_block_id>
```

## LLM interaction

Submit a prompt against a target:

```bash
curl -s -X POST http://127.0.0.1:8000/api/llm/interact \
  -H 'Content-Type: application/json' \
  -d '{
    "target_id":"<target_id>",
    "ip_address":"10.129.31.195",
    "prompt":"Summarize the current findings and propose the next safe step.",
    "model":"auto",
    "context_block_ids":[],
    "include_services":true,
    "include_findings":true,
    "include_observations":true,
    "include_pending_actions":true,
    "include_timeline":false
  }'
```

Read the recent LLM prompt log:

```bash
curl -s http://127.0.0.1:8000/api/llm/prompts
```

Read the joined prompt, response, conversation, and planner trace:

```bash
curl -s 'http://127.0.0.1:8000/api/llm/trace?target_id=<target_id>&limit=20'
```

Prompt and response events are appended to `state/logs/llm_prompts.jsonl`. Planner events are appended to `state/logs/llm_planner.jsonl`.

## Planner control

Run one planner step for a target:

```bash
curl -s -X POST http://127.0.0.1:8000/api/targets/<target_id>/planner/step
```

Enable or disable the background planner worker:

```bash
curl -s -X POST http://127.0.0.1:8000/api/llm/planner/start
curl -s -X POST http://127.0.0.1:8000/api/llm/planner/stop
```

Read planner status:

```bash
curl -s http://127.0.0.1:8000/api/llm/planner
```

Planner settings live in `state/settings/runtime.json`. Important fields include `autoplan_enabled`, `autoplan_interval_seconds`, `autoplan_max_actions_per_turn`, `autoplan_prompt`, and `command_allowlist`.

## Smoke-test sequence

This is the shortest verified workflow that exercises the core app instead of only the health endpoints:

1. Create a target with `POST /api/targets/start`.
2. Read `GET /api/targets/<target_id>` until the baseline enumeration finishes.
3. Read `GET /api/targets/<target_id>/report`.
4. Send a prompt to `POST /api/llm/interact`.
5. Delete the target with `DELETE /api/targets/<target_id>`.

## Notes

- Quote URLs containing `?` when using `zsh`, for example `curl -s 'http://127.0.0.1:8000/api/targets/<target_id>/logs?limit=20'`.
- The backend loads `.env` and then `.htb-codex.env` with `override=False`; existing shell or `.env` values win when keys overlap.
- `state/targets/<target_id>/` holds the JSON state, logs, and scan artifacts for each target.
- For LLM analysis, prefer `/api/llm/trace` over raw prompt-log parsing when the backend is running, because it joins prompt, response, conversation, and planner metadata.
