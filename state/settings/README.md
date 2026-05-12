# Runtime Settings

This folder stores mutable application settings.

## `runtime.json`

Written by:

- `_save_runtime_settings()` in `backend/htbmc/app.py`
- `POST /api/settings/llm`
- `PUT /api/settings/commands`
- `POST /api/settings/commands`

Important fields:

- `ollama_base_url`
- `ollama_tailscale_host`
- `ollama_timeout_seconds`
- `default_model`
- `temperature`
- `num_ctx`
- `autoplan_enabled`
- `autoplan_interval_seconds`
- `autoplan_max_actions_per_turn`
- `autoplan_prompt`
- `system_prompt`
- `command_allowlist`

Example:

```bash
cat state/settings/runtime.json
curl -s http://127.0.0.1:8000/api/settings
```

If a key is missing, `backend/htbmc/app.py` fills defaults from `DEFAULT_LLM_SETTINGS`. A missing file is valid and means the app will use defaults until settings are changed.
