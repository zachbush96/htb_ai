import React from 'react'
import { badgeClass } from '../lib/app-utils'
import { Panel } from '../components/primitives'
import { SupportActionMenu, SupportCard, SupportModal, SupportNotice, SupportWhy, useSupportActions } from './support-actions'

function modelWhy(backendHealth) {
  if (backendHealth?.ollama?.reachable) {
    return `Model health is marked reachable because the backend probe to ${backendHealth.ollama.base_url} succeeded and returned ${backendHealth.ollama.models?.length || 0} advertised model entries.`
  }
  return `Model health is marked offline because the backend probe could not reach the configured Ollama endpoint. The current error path is ${backendHealth?.ollama?.error || 'unknown'}.`
}

function backendWhy(backendHealth) {
  return [
    `The backend card reflects the /healthz payload status of ${backendHealth?.status || 'offline'}.`,
    backendHealth?.state_dir ? `Its active state directory is ${backendHealth.state_dir}.` : 'No state directory was returned by the backend health payload.',
    'Use raw diagnostics when you need the full probe payload instead of the summarized card values.',
  ].join(' ')
}

export function TeamView({ backendHealth }) {
  const { notice, modal, closeModal, copyValue, openJson, openUrl } = useSupportActions()
  const ollamaUrl = backendHealth?.ollama?.base_url || null

  return (
    <div className="view-grid">
      <Panel
        title="Team Console"
        className="wide"
        actions={(
          <SupportActionMenu
            items={[
              {
                id: 'copy-state-dir',
                label: 'Copy state dir',
                description: 'Copy the active backend state directory.',
                disabled: !backendHealth?.state_dir,
                onSelect: () => copyValue('State dir', backendHealth?.state_dir || ''),
              },
              {
                id: 'raw-health',
                label: 'View raw diagnostics',
                description: 'Inspect the full backend /healthz payload.',
                disabled: !backendHealth,
                onSelect: () => openJson('Backend health payload', backendHealth || {}, {
                  description: 'This is the raw /healthz response currently backing the team cards.',
                }),
              },
              {
                id: 'open-ollama',
                label: 'Open Ollama in browser',
                description: 'Open the configured model endpoint in a new tab.',
                disabled: !ollamaUrl,
                onSelect: () => openUrl('Ollama', ollamaUrl),
              },
            ]}
          />
        )}
      >
        <SupportNotice notice={notice} />
        <div className="team-grid">
          <SupportCard
            meta="operator"
            title="Red Team Operator"
            subtitle="Primary human-in-the-loop reviewer for queued actions and support decisions."
          >
            <em className="badge good">online</em>
            <SupportWhy title="Ask why" body="This card is static by design. It anchors the admin console around the operator role that approves actions and interprets diagnostics." />
          </SupportCard>

          <SupportCard
            meta="backend"
            title={backendHealth?.state_dir || 'state unavailable'}
            subtitle={`Health status: ${backendHealth?.status || 'offline'}`}
            menuItems={[
              {
                id: 'copy-backend-dir',
                label: 'Copy state dir',
                description: 'Copy the backend state directory.',
                disabled: !backendHealth?.state_dir,
                onSelect: () => copyValue('State dir', backendHealth?.state_dir || ''),
              },
              {
                id: 'copy-backend-status',
                label: 'Copy backend status',
                description: 'Copy the summarized backend health state.',
                onSelect: () => copyValue('Backend status', backendHealth?.status || 'offline'),
              },
              {
                id: 'raw-backend',
                label: 'View raw diagnostics',
                description: 'Show the full backend card payload.',
                disabled: !backendHealth,
                onSelect: () => openJson('Backend card diagnostics', backendHealth || {}, {
                  description: 'Raw backend metadata from the current /healthz response.',
                }),
              },
            ]}
          >
            <em className={badgeClass(backendHealth?.status || 'offline')}>{backendHealth?.status || 'offline'}</em>
            <SupportWhy title="Ask why" body={backendWhy(backendHealth)} />
          </SupportCard>

          <SupportCard
            meta="model"
            title={backendHealth?.ollama?.base_url || 'not configured'}
            subtitle={backendHealth?.ollama?.models?.length ? `${backendHealth.ollama.models.length} model(s) advertised` : 'No models advertised yet'}
            menuItems={[
              {
                id: 'open-model',
                label: 'Open Ollama in browser',
                description: 'Open the configured Ollama base URL.',
                disabled: !ollamaUrl,
                onSelect: () => openUrl('Ollama', ollamaUrl),
              },
              {
                id: 'copy-model-base',
                label: 'Copy model base',
                description: 'Copy the Ollama base URL used by the backend.',
                disabled: !ollamaUrl,
                onSelect: () => copyValue('Model base', ollamaUrl || ''),
              },
              {
                id: 'raw-model',
                label: 'View raw diagnostics',
                description: 'Inspect the raw Ollama probe payload.',
                disabled: !backendHealth?.ollama,
                onSelect: () => openJson('Ollama probe payload', backendHealth?.ollama || {}, {
                  description: 'Raw model reachability data from backend health checks.',
                }),
              },
            ]}
          >
            <em className={badgeClass(backendHealth?.ollama?.reachable ? 'ready' : 'blocked')}>
              {backendHealth?.ollama?.reachable ? 'reachable' : 'offline'}
            </em>
            {backendHealth?.ollama?.models?.length ? (
              <span style={{ color: '#aab4b7', overflowWrap: 'anywhere' }}>{backendHealth.ollama.models.join(', ')}</span>
            ) : null}
            <SupportWhy title="Ask why" body={modelWhy(backendHealth)} />
          </SupportCard>
        </div>
        <SupportModal modal={modal} onClose={closeModal} />
      </Panel>
    </div>
  )
}
