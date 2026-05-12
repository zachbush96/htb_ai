# Legacy State Repo Note

This file used to contain a shell snippet for initializing the runtime state directory as a Git repo.

Current state guidance:

- Runtime state defaults to `./state` through `env.example`.
- `HTBMC_STATE_DIR` can move state to another folder.
- Generated state may contain target evidence, command output, prompt logs, and operational notes.
- Do not commit sensitive runtime state unless you intentionally curated it as a fixture.

See [state/README.md](./state/README.md) for the current state layout.
