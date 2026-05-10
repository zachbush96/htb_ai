# HTB Mission Control MVP

A mobile and desktop mission-control interface for HackTheBox PwnBox workflows.

The design goal is simple: keep the full power of the PwnBox and Kali tooling, but replace terminal-first workflows with target state, jobs, findings, approvals, evidence, listeners, reports, and a Codex-backed agent loop.

## What V1 includes

- FastAPI backend
- React/Vite frontend
- Target case folders saved as JSON and JSONL
- Async job runner with output capture
- Command risk classifier
- Approval queue for risky actions
- Evidence and report tracking
- Automatic hostname tracking and `/etc/hosts` update attempts
- Listener tracking
- Credential and finding stores
- Global mistake memory
- Codex CLI bridge using `codex exec`
- Heuristic fallback planner when Codex is unavailable
- GitHub state sync with sanitizer and auto push hooks
- Mobile-first UI plus desktop operator layout

## Intended environment

This is intended to run inside an HTB PwnBox or your own authorized lab environment.

Do not expose this app publicly. Use Tailscale or local-only access.

## Quick start

```bash
cd htb-mission-control
cp .env.example .env
./scripts/bootstrap.sh
./scripts/run_dev.sh
```

Then open:

```text
http://127.0.0.1:8000
```

Or from Tailscale:

```text
http://<pwnbox-tailscale-ip>:8000
```

## Persistent storage

Default state directory:

```text
$HOME/my_data/htb-mission-control-state
```

Override it:

```bash
export HTBMC_STATE_DIR=/path/to/persistent/state
```

## GitHub state sync

Set a private repo remote in `.env`:

```bash
HTBMC_STATE_GIT_REMOTE=git@github.com:yourname/htb-mission-state.git
HTBMC_AUTO_PUSH=true
```

The app auto commits and pushes after major events. The sanitizer blocks common secret paths and `.env` files.

## Codex integration

The backend calls Codex in non-interactive mode through `codex exec`, with JSON events enabled, a JSON schema, read-only sandboxing, and `--ask-for-approval never`. Codex proposes actions. The backend policy engine decides whether to run, queue, or request approval.

V1 does not rely on Codex to enforce approvals. Approval is enforced by the backend.

Useful environment values:

```bash
CODEX_BIN=codex
CODEX_PROFILE=htb-agent
HTBMC_CODEX_ENABLED=true
```

If Codex is missing or fails, the fallback planner still gives basic nmap/http suggestions.

## Safety model

- Safe recon runs automatically.
- Listener creation is logged, not approval-gated.
- Single credential tests are allowed, but spraying/brute force requires approval.
- Exploit download metadata requires approval.
- Exploit execution requires approval.
- Uploads, reverse shells, brute force, and file execution are approval-gated.
- Out-of-scope targets are blocked.

## Repo layout

```text
backend/          FastAPI app and operation engine
frontend/         React/Vite UI
prompts/          Agent prompts
schemas/          JSON schemas for Codex output
skills/           Codex skill packages
scripts/          Bootstrap and run scripts
state_template/   Empty persistent state skeleton
```

## MVP flow

1. Add target IP.
2. Backend creates a case folder.
3. Start initial recon.
4. Job runner captures raw output.
5. Parser extracts hostnames, ports, and findings.
6. Agent proposes next actions.
7. Risky proposals become approval cards.
8. Approved jobs run and update timeline/evidence/report.
9. Git sync snapshots the state.

## Known V1 limitations

- Jobs running during a PwnBox reset will be marked stale on next startup.
- `/etc/hosts` update requires write access. If it fails, the timeline records the suggested line.
- The frontend is intentionally functional-first, not final-polish.
- Codex structured output depends on your configured provider quality.
- No raw command box in V1 by design.
