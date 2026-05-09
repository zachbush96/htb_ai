# PwnBox Setup and Test Guide

## Prerequisites

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip nodejs npm
```

## Setup

```bash
git clone <YOUR_REPO_URL> htb_ai
cd htb_ai
cp env.example .env
```

Optional `.env` values for PwnBox:

```dotenv
HTBMC_BIND_HOST=0.0.0.0
HTBMC_PORT=8000
HTBMC_STATE_DIR=$HOME/my_data/htb-mission-control-state
```

## Bootstrap dependencies

```bash
./scripts/bootstrap.sh
```

## Run backend

```bash
./scripts/run_dev.sh
```

Open: `http://127.0.0.1:8000` (or your PwnBox/Tailscale IP).

## Run frontend (second terminal)

```bash
cd frontend
npm run dev
```

Open: `http://127.0.0.1:5173`.

## Validation checks

```bash
curl -s http://127.0.0.1:8000/
curl -s http://127.0.0.1:8000/healthz
curl -I http://127.0.0.1:5173
```

## One-shot quick start

```bash
sudo apt update && sudo apt install -y python3 python3-venv python3-pip nodejs npm
git clone <YOUR_REPO_URL> htb_ai
cd htb_ai
cp env.example .env
./scripts/bootstrap.sh
```
