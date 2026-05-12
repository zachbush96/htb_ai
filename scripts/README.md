# Scripts

These are the supported project launchers. Run them from any directory; each script resolves the repository root before doing work.

## `bootstrap.sh`

Installs backend and frontend dependencies.

What it does:

- copies `env.example` to `.env` if `.env` is missing
- selects Python from `HTBMC_PYTHON_BIN`, `python3.13`, `python3.12`, `python3.11`, then `python3`
- accepts only Python `3.11`, `3.12`, or `3.13`
- rebuilds `.venv` if the existing virtualenv uses a different Python minor version
- installs `backend/requirements.txt`
- runs `npm install` in `frontend/` when `npm` exists

Example:

```bash
HTBMC_PYTHON_BIN=python3.13 ./scripts/bootstrap.sh
```

## `run_dev.sh`

Starts the FastAPI backend.

Inputs:

- `.venv/bin/activate`
- `backend/htbmc/app.py`
- `.env`
- `.htb-codex.env`

Environment overrides:

```bash
HTBMC_BIND_HOST=0.0.0.0 HTBMC_PORT=8001 ./scripts/run_dev.sh
```

Important output locations:

- `HTBMC_STATE_DIR` controls target state, logs, artifacts, and settings.
- `/healthz` reports the resolved state directory and Ollama diagnostics.

## `run_frontend.sh`

Starts the React/Vite UI.

Inputs:

- `frontend/package.json`
- `frontend/node_modules/`
- `frontend/src/main.jsx`

Environment overrides:

```bash
HTBMC_FRONTEND_HOST=0.0.0.0 HTBMC_FRONTEND_PORT=5174 ./scripts/run_frontend.sh
```

## Root wrapper

`../run_dev.sh` is a compatibility wrapper around `scripts/run_dev.sh` for older shell history and notes.

## Common startup

```bash
./scripts/bootstrap.sh
./scripts/run_dev.sh
```

Second terminal:

```bash
./scripts/run_frontend.sh
```
