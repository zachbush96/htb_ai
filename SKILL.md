# Legacy Bootstrap Note

This file used to contain an early bootstrap shell script even though its extension is `.md`. The supported bootstrap path is now:

```bash
./scripts/bootstrap.sh
./scripts/run_dev.sh
./scripts/run_frontend.sh
```

Use [scripts/README.md](./scripts/README.md) for the current launcher behavior.

Retained context:

- Early versions created a state directory under `$HOME/my_data/htb-mission-control-state`.
- Current local defaults are in `env.example`, which sets `HTBMC_STATE_DIR=./state`.
- Current backend code reads state from `backend/htbmc/app.py::STATE_DIR`.

For LLM analysis, treat this file as historical context only, not an active script.
