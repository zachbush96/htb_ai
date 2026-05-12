# Legacy Backend Launcher Note

This file used to contain an early backend launcher shell script despite the `.md` extension. The active backend launcher is:

```bash
./scripts/run_dev.sh
```

Current behavior:

- activates `.venv`
- sets `PYTHONPATH` to include `backend/`
- reads `HTBMC_BIND_HOST` and `HTBMC_PORT`
- starts `uvicorn htbmc.app:app --app-dir backend`

See [scripts/README.md](./scripts/README.md) for examples and environment overrides.
