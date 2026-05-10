# PwnBox Setup

This is the raw PwnBox bring-up path for HTB Mission Control.

## Packages

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip nodejs npm nmap
```

## Project setup

```bash
git clone <YOUR_REPO_URL> ~/htb_ai
cd ~/htb_ai
cp -n env.example .env
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r backend/requirements.txt
cd frontend
npm install
cd ..
```

If you want the backend reachable from outside the box, set:

```dotenv
HTBMC_BIND_HOST=0.0.0.0
HTBMC_PORT=8000
HTBMC_STATE_DIR=$HOME/htb_ai/state
```

## Start the backend

Run in terminal 1:

```bash
cd ~/htb_ai
source .venv/bin/activate
export PYTHONPATH="$PWD/backend:${PYTHONPATH:-}"
uvicorn htbmc.app:app --host "${HTBMC_BIND_HOST:-0.0.0.0}" --port "${HTBMC_PORT:-8000}" --app-dir backend
```

## Start the frontend

Run in terminal 2:

```bash
cd ~/htb_ai/frontend
npm run dev -- --host 0.0.0.0 --port 5173
```

Open:

- Backend API: `http://127.0.0.1:8000`
- Frontend UI: `http://127.0.0.1:5173`

If you are connecting remotely, replace `127.0.0.1` with the PwnBox IP or Tailscale IP.

## Validation

```bash
curl -s http://127.0.0.1:8000/
curl -s http://127.0.0.1:8000/healthz
curl -I http://127.0.0.1:5173
```

Create a test target:

```bash
curl -s -X POST http://127.0.0.1:8000/api/targets/start \
  -H 'Content-Type: application/json' \
  -d '{"ip_address":"127.0.0.1","label":"pwnbox smoke test"}'
```

Read logs:

```bash
curl -s 'http://127.0.0.1:8000/api/targets/<target_id>/logs?limit=20'
```

## Scripted alternative

```bash
cd ~/htb_ai
./scripts/bootstrap.sh
./scripts/run_dev.sh
```
