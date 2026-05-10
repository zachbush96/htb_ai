# API Quick Reference

Base URL: `http://127.0.0.1:8000`

## Health and runtime

```bash
curl -s http://127.0.0.1:8000/
curl -s http://127.0.0.1:8000/healthz
curl -s http://127.0.0.1:8000/api/settings
curl -s http://127.0.0.1:8000/api/diagnostics/ollama
curl -s http://127.0.0.1:8000/api/reports/overview
```

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

Stop a running execution:

```bash
curl -s -X POST http://127.0.0.1:8000/api/targets/<target_id>/jobs/<job_id>/stop \
  -H 'Content-Type: application/json' \
  -d '{"note":"stop requested from curl"}'

curl -s -X POST http://127.0.0.1:8000/api/targets/<target_id>/actions/<action_id>/stop \
  -H 'Content-Type: application/json' \
  -d '{"note":"stop requested from curl"}'
```

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

## Notes

- Quote URLs containing `?` when using `zsh`, for example `curl -s 'http://127.0.0.1:8000/api/targets/<target_id>/logs?limit=20'`.
- The backend loads `.env` and then `.htb-codex.env`.
- `state/targets/<target_id>/` holds the JSON state, logs, and scan artifacts for each target.
