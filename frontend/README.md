# Frontend

The frontend is a React/Vite operator UI for the FastAPI backend.

## UI Preview

The current local UI is built around an operator-first workflow: start in the conversation loop, pivot into the mission dashboard, review evidence in reports and loot, and keep execution plus model settings visible without leaving the app shell.

![Conversation view](../docs/images/ui/conversation-view.png)

<table>
  <tr>
    <td><img src="../docs/images/ui/dashboard-view.png" alt="Dashboard view"></td>
    <td><img src="../docs/images/ui/reports-view.png" alt="Reports view"></td>
  </tr>
  <tr>
    <td><img src="../docs/images/ui/jobs-view.png" alt="Jobs view"></td>
    <td><img src="../docs/images/ui/settings-view.png" alt="Settings view"></td>
  </tr>
</table>

## Primary Files

- `src/main.jsx`: app shell, polling, active target selection, API request helpers, and route/view selection.
- `src/views/dashboard.jsx`: target overview, active jobs, actions, findings, timeline, and recommendations.
- `src/views/targets.jsx`: target list and target management.
- `src/views/jobs.jsx`: job and action execution visibility.
- `src/views/approvals.jsx`: approval, deny, remove, and stop workflows.
- `src/views/conversation.jsx`: operator-to-LLM interaction.
- `src/views/settings.jsx`: LLM, planner, and command policy settings.
- `src/views/reports.jsx`: target-scoped and overview reports.
- `src/views/loot.jsx`: completed artifact review.
- `src/views/timeline.jsx`: event review.
- `src/components/primitives.jsx`: shared UI primitives.
- `src/components/action-kit.jsx`: action rendering helpers.
- `src/lib/app-utils.js`: formatting, API display, and target helper utilities.

## Screen Map

- `Conversation`: target-linked assistant loop, saved context blocks, transcript review, pending approvals, and live execution visibility.
- `Dashboard`: scorecard-style target posture, findings density, service counts, and recommended next steps.
- `Jobs`: running and completed command execution with output metadata and artifact paths.
- `Reports`: target summary cards plus report-level counts for services, findings, observations, and completed actions.
- `Loot`: collected observations and artifact review actions.
- `Settings`: API base configuration, runtime settings, model diagnostics, prompt visibility, and planner controls.

## Development

Start the backend first:

```bash
./scripts/run_dev.sh
```

Start the frontend:

```bash
./scripts/run_frontend.sh
```

Direct Vite commands:

```bash
cd frontend
npm run dev -- --host 127.0.0.1 --port 5173
npm run build
```

## API Expectations

The frontend expects these backend endpoints:

- `GET /healthz`
- `GET /api/settings`
- `GET /api/targets`
- `GET /api/targets/<target_id>`
- `GET /api/targets/<target_id>/logs`
- `GET /api/targets/<target_id>/report`
- `POST /api/llm/interact`
- `GET /api/llm/trace`
- action approval, deny, delete, and stop endpoints under `/api/targets/<target_id>/actions/`

When the UI looks stale, inspect `src/main.jsx` polling and then compare the backend payload in `state/targets/<target_id>/target.json`.
