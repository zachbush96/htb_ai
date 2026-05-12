# PwnBox Setup

Use this guide when you want the same project running on a Linux host or HTB PwnBox instead of the local Mac checkout.

## System packages

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip nodejs npm nmap
```

## Clone and bootstrap

```bash
git clone <YOUR_REPO_URL> ~/htb_ai
cd ~/htb_ai
./scripts/bootstrap.sh
```

If you prefer the raw path instead of the helper script:

```bash
cp -n env.example .env
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r backend/requirements.txt
cd frontend
npm install
cd ..
```

## Recommended environment

For remote access from another machine, set these values in `.env` or `.htb-codex.env`:

```dotenv
HTBMC_BIND_HOST=0.0.0.0
HTBMC_PORT=8000
HTBMC_FRONTEND_HOST=0.0.0.0
HTBMC_FRONTEND_PORT=5173
HTBMC_STATE_DIR=$HOME/htb_ai/state
```

Use a stable `HTBMC_STATE_DIR` on PwnBox. Target IDs, reports, action logs, prompt traces, and planner traces are all file-backed, so changing the state path mid-operation makes the UI look like it lost history.

If you want LLM-backed workflows, also set:

```dotenv
OLLAMA_BASE_URL=http://your-ollama-host:11434
```

## Start the stack

Backend, terminal 1:

```bash
cd ~/htb_ai
HTBMC_BIND_HOST=0.0.0.0 HTBMC_PORT=8000 ./scripts/run_dev.sh
```

Frontend, terminal 2:

```bash
cd ~/htb_ai
HTBMC_FRONTEND_HOST=0.0.0.0 HTBMC_FRONTEND_PORT=5173 ./scripts/run_frontend.sh
```

If you prefer raw commands:

```bash
cd ~/htb_ai
source .venv/bin/activate
export PYTHONPATH="$PWD/backend:${PYTHONPATH:-}"
uvicorn htbmc.app:app --host 0.0.0.0 --port 8000 --app-dir backend
```

```bash
cd ~/htb_ai/frontend
npm run dev -- --host 0.0.0.0 --port 5173
```

Use the PwnBox IP or Tailscale IP in place of `127.0.0.1` when you connect from another machine.

## Validation

```bash
curl -s http://127.0.0.1:8000/
curl -s http://127.0.0.1:8000/healthz
curl -I http://127.0.0.1:5173
```

Create a smoke-test target:

```bash
curl -s -X POST http://127.0.0.1:8000/api/targets/start \
  -H 'Content-Type: application/json' \
  -d '{"ip_address":"127.0.0.1","label":"pwnbox smoke test"}'
```

Read the report and logs:

```bash
curl -s http://127.0.0.1:8000/api/targets/<target_id>/report
curl -s 'http://127.0.0.1:8000/api/targets/<target_id>/logs?limit=20'
```

On a live HTB target, replace `127.0.0.1` in the target-create payload with the machine IP. Keep API URLs pointed at the local backend unless you intentionally exposed the backend on another interface.

## State and evidence on PwnBox

When using the recommended environment above, evidence lands under:

```text
~/htb_ai/state/
  logs/
  settings/
  targets/<target_id>/
```

For LLM-assisted review, inspect these files in order:

1. `~/htb_ai/state/targets/<target_id>/target.json`
2. `~/htb_ai/state/targets/<target_id>/logs/activity.jsonl`
3. `~/htb_ai/state/targets/<target_id>/artifacts/scans/*.nmap`
4. `~/htb_ai/state/targets/<target_id>/artifacts/actions/*.log`
5. `~/htb_ai/state/logs/llm_prompts.jsonl`
6. `~/htb_ai/state/logs/llm_planner.jsonl`

## Notes

- `bootstrap.sh` supports Python `3.11` through `3.13`.
- `run_dev.sh` starts only the backend; use `run_frontend.sh` for the Vite UI.
- If you transferred this repo from macOS, make sure you did not copy `.venv`, `state/`, or `._*` metadata files into the Linux workspace.
