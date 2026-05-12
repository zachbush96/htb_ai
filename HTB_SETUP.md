# HTB Mission Control Setup

This is the verified bring-up path for the local project checkout at `/Users/zachbush/Downloads/htb_ai-main`.

## Prerequisites

- Python `3.11`, `3.12`, or `3.13`
- `node` and `npm`
- `nmap`

Check them:

```bash
python3 --version
python3.11 --version || true
python3.13 --version || true
node --version
npm --version
nmap --version | head -n 1
```

If `python3` resolves to an unsupported version such as `3.14`, pin the interpreter explicitly:

```bash
export HTBMC_PYTHON_BIN=python3.13
```

## Bootstrap the repo

```bash
cd /Users/zachbush/Downloads/htb_ai-main
./scripts/bootstrap.sh
```

What bootstrap does:

- copies `env.example` to `.env` if `.env` does not exist
- selects a supported Python interpreter
- recreates `.venv` if it points at the wrong Python minor version
- installs backend requirements
- installs frontend dependencies

The helper is documented in [scripts/README.md](./scripts/README.md). It is the preferred setup path because it rejects unsupported Python versions and rebuilds `.venv` when the selected minor version changes.

## Start the stack

Run the backend in terminal 1:

```bash
cd /Users/zachbush/Downloads/htb_ai-main
./scripts/run_dev.sh
```

Run the frontend in terminal 2:

```bash
cd /Users/zachbush/Downloads/htb_ai-main
./scripts/run_frontend.sh
```

Defaults:

- backend: `http://127.0.0.1:8000`
- frontend: `http://127.0.0.1:5173`

When both processes are up, open `http://127.0.0.1:5173`. A healthy running UI should look like this:

![HTB Mission Control conversation view after local startup](docs/images/ui/conversation-view.png)

You should see the left navigation, backend/model health badges in the header, and populated operator panels if your `state/` directory already contains target data.

Optional overrides:

```bash
HTBMC_BIND_HOST=0.0.0.0 HTBMC_PORT=8001 ./scripts/run_dev.sh
HTBMC_FRONTEND_HOST=0.0.0.0 HTBMC_FRONTEND_PORT=5174 ./scripts/run_frontend.sh
```

## Raw commands

Use this path if you do not want the helper scripts:

```bash
cd /Users/zachbush/Downloads/htb_ai-main
cp -n env.example .env
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r backend/requirements.txt
cd frontend
npm install
cd ..
```

Backend:

```bash
cd /Users/zachbush/Downloads/htb_ai-main
source .venv/bin/activate
export PYTHONPATH="$PWD/backend:${PYTHONPATH:-}"
uvicorn htbmc.app:app --host 127.0.0.1 --port 8000 --app-dir backend
```

Frontend:

```bash
cd /Users/zachbush/Downloads/htb_ai-main/frontend
npm run dev -- --host 127.0.0.1 --port 5173
```

## Ollama configuration

LLM-backed features are optional for basic startup but required for `/api/llm/interact`.

The backend loads:

1. `.env`
2. `.htb-codex.env` with `override=False`

If the same key appears in both files, the `.env` value wins. Put private local values in `.htb-codex.env`, but remove or leave the matching `.env` key empty if you want that value to take effect.

Set one of these in either file:

```dotenv
OLLAMA_BASE_URL=http://your-ollama-host:11434
OLLAMA_TAILSCALE_HOST=your-ollama-host:11434
HTBMC_OLLAMA_TIMEOUT_SECONDS=5
```

Validate the backend-to-Ollama path:

```bash
curl -s http://127.0.0.1:8000/healthz
curl -s http://127.0.0.1:8000/api/diagnostics/ollama
curl -s http://127.0.0.1:8000/api/settings
```

Prompt and response traces are saved in `state/logs/llm_prompts.jsonl`. Autonomous planner events are saved in `state/logs/llm_planner.jsonl`. See [state/logs/README.md](./state/logs/README.md) before asking an LLM to inspect those logs directly.

## Runtime state

By default, this checkout writes runtime data under `./state` because `env.example` sets:

```dotenv
HTBMC_STATE_DIR=./state
```

Important generated paths:

- `state/settings/runtime.json`: LLM settings, planner options, and command allowlist.
- `state/targets/<target_id>/target.json`: canonical target state.
- `state/targets/<target_id>/logs/activity.jsonl`: target event stream.
- `state/targets/<target_id>/artifacts/scans/`: nmap evidence.
- `state/targets/<target_id>/artifacts/actions/`: approved action evidence.

These folders include README files with examples of what each file means.

## Smoke test the full workflow

Basic service checks:

```bash
curl -s http://127.0.0.1:8000/
curl -s http://127.0.0.1:8000/healthz
curl -I http://127.0.0.1:5173
```

Create a target and queue baseline enumeration:

```bash
curl -s -X POST http://127.0.0.1:8000/api/targets/start \
  -H 'Content-Type: application/json' \
  -d '{"ip_address":"127.0.0.1","label":"docs smoke test"}'
```

Inspect the target:

```bash
curl -s http://127.0.0.1:8000/api/targets
curl -s http://127.0.0.1:8000/api/targets/<target_id>
curl -s http://127.0.0.1:8000/api/targets/<target_id>/report
curl -s 'http://127.0.0.1:8000/api/targets/<target_id>/logs?limit=20'
```

Exercise the LLM endpoint:

```bash
curl -s -X POST http://127.0.0.1:8000/api/llm/interact \
  -H 'Content-Type: application/json' \
  -d '{
    "target_id":"<target_id>",
    "ip_address":"127.0.0.1",
    "prompt":"Summarize the current findings and propose the next safe step in two bullets.",
    "model":"auto",
    "context_block_ids":[],
    "include_services":true,
    "include_findings":true,
    "include_observations":true,
    "include_pending_actions":true,
    "include_timeline":false
  }'
```

Delete the smoke-test target when you are done:

```bash
curl -s -X DELETE http://127.0.0.1:8000/api/targets/<target_id>
```

If deletion returns HTTP `409`, the target still has a running job or action. Either wait for it to finish or stop it first with the endpoints listed in [API.md](./API.md#execution-control).
