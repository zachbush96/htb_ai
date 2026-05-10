# HTB Mission Control

HTB Mission Control is a FastAPI backend plus a React/Vite frontend for driving HTB target enumeration, approvals, findings, artifacts, and Codex-assisted next steps from one UI.

## Verified local bring-up

These commands were validated on this Mac on May 9, 2026.

### Prerequisites

- Python `3.11`, `3.12`, or `3.13`
- `node` and `npm`
- `nmap`

Check them:

```bash
python3.11 --version
node --version
npm --version
nmap --version | head -n 1
```

### Raw setup commands

Use `python3.11` explicitly if `python3` resolves to `3.14`, because `pydantic-core==2.27.2` does not build cleanly there.

```bash
cd /Users/zachbush/Downloads/htb_ai-main
cp -n env.example .env
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r backend/requirements.txt
cd frontend
npm install
cd ..
```

### Start the backend

Run in terminal 1:

```bash
cd /Users/zachbush/Downloads/htb_ai-main
source .venv/bin/activate
export PYTHONPATH="$PWD/backend:${PYTHONPATH:-}"
uvicorn htbmc.app:app --host 127.0.0.1 --port 8000 --app-dir backend
```

### Start the frontend

Run in terminal 2:

```bash
cd /Users/zachbush/Downloads/htb_ai-main/frontend
npm run dev -- --host 127.0.0.1 --port 5173
```

Open:

- Backend API: `http://127.0.0.1:8000`
- Frontend UI: `http://127.0.0.1:5173`

## Validation commands

These are the exact checks used during bring-up.

```bash
curl -s http://127.0.0.1:8000/
curl -s http://127.0.0.1:8000/healthz
curl -I http://127.0.0.1:5173
```

Create a local test target and start enumeration:

```bash
curl -s -X POST http://127.0.0.1:8000/api/targets/start \
  -H 'Content-Type: application/json' \
  -d '{"ip_address":"127.0.0.1","label":"local raw bring-up test"}'
```

Fetch target details:

```bash
curl -s http://127.0.0.1:8000/api/targets
curl -s http://127.0.0.1:8000/api/targets/<target_id>
```

Fetch activity logs. Quote the URL in `zsh` so `?limit=20` is not treated as glob syntax:

```bash
curl -s 'http://127.0.0.1:8000/api/targets/<target_id>/logs?limit=20'
```

## Optional Ollama wiring

The backend loads both `.env` and `.htb-codex.env`. To enable remote Ollama diagnostics, set one of these:

```dotenv
OLLAMA_BASE_URL=http://100.102.78.116:11434
OLLAMA_TAILSCALE_HOST=100.102.78.116:11434
```

Then re-check:

```bash
curl -s http://127.0.0.1:8000/healthz
curl -s http://127.0.0.1:8000/api/diagnostics/ollama
```

## Scripted path

If you want the repo helpers instead of the raw commands:

```bash
cd /Users/zachbush/Downloads/htb_ai-main
./scripts/bootstrap.sh
./scripts/run_dev.sh
```

The bootstrap script now prefers Python `3.11` to `3.13` automatically and fails fast on unsupported interpreter versions.
