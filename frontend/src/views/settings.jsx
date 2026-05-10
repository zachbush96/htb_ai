import React from 'react'
import { cleanDisplayText, formatDateTime } from '../lib/app-utils'
import { EmptyState, Panel } from '../components/primitives'
import { SupportActionMenu, SupportCard, SupportModal, SupportNotice, SupportWhy, useSupportActions } from './support-actions'

function promptWhy(prompt, llmPrompts) {
  return [
    `This prompt was recorded for target ${prompt?.ip_address || 'unknown'} using model ${prompt?.model || 'unknown'}.`,
    `The operator request was "${prompt?.operator_prompt || 'not preserved'}".`,
    llmPrompts?.user_prompt_template
      ? 'Mission Control expands the operator request into the stored user prompt template so later review can reconstruct the exact model input.'
      : 'The current prompt template is unavailable, so only the recorded prompt text can be reviewed.',
  ].join(' ')
}

function templateWhy(kind) {
  if (kind === 'system') {
    return 'The system prompt defines the standing mission-control rules that every LLM request inherits before target context and operator text are attached.'
  }
  return 'The user prompt template shows how Mission Control expands an operator request into the final LLM input, including target IP and serialized target context.'
}

export function SettingsView({ apiBase, setApiBase, uiSettings, setUiSettings, runtimeSettings, diagnostics, testSettings, llmPrompts }) {
  const { notice, modal, closeModal, copyValue, openText, openJson, openUrl } = useSupportActions()

  function updateSetting(key, value) {
    setUiSettings((current) => ({ ...current, [key]: value }))
  }

  const ollamaBase = diagnostics?.ollama?.base_url || runtimeSettings?.ollama_base_url || null
  const promptHistory = llmPrompts?.recent_prompts?.slice().reverse() || []

  return (
    <div className="settings-grid">
      <Panel
        title="Connection"
        actions={(
          <SupportActionMenu
            items={[
              {
                id: 'copy-api-base',
                label: 'Copy API base',
                description: 'Copy the frontend API base URL.',
                onSelect: () => copyValue('API base', apiBase),
              },
              {
                id: 'view-connection-diagnostics',
                label: 'View raw diagnostics',
                description: 'Inspect the full settings and Ollama diagnostics payload.',
                disabled: !diagnostics && !runtimeSettings,
                onSelect: () => openJson('Connection diagnostics', { diagnostics, runtimeSettings }, {
                  description: 'Combined connection and runtime payload currently shown on the settings page.',
                }),
              },
              {
                id: 'open-ollama-browser',
                label: 'Open Ollama in browser',
                description: 'Open the configured Ollama base URL when present.',
                disabled: !ollamaBase,
                onSelect: () => openUrl('Ollama', ollamaBase),
              },
            ]}
          />
        )}
      >
        <SupportNotice notice={notice} />
        <label>
          API base
          <input value={apiBase} onChange={(event) => setApiBase(event.target.value)} placeholder="http://127.0.0.1:8000" />
        </label>
        <div className="button-row">
          <button type="button" onClick={() => setApiBase('http://127.0.0.1:8000')}>Use Default</button>
          <button className="primary" type="button" onClick={testSettings}>Test Connection</button>
        </div>
        <dl className="settings-list">
          <div><dt>Status</dt><dd>{diagnostics?.settings ? 'connected' : 'not tested'}</dd></div>
          <div><dt>Ollama</dt><dd>{diagnostics?.ollama?.reachable ? 'reachable' : cleanDisplayText(diagnostics?.ollama?.error, 'unknown')}</dd></div>
        </dl>
        <SupportWhy title="Ask why" body="The connection panel is driven by the most recent /api/settings call. It tells you whether the frontend can reach the backend and whether the backend can reach its configured Ollama endpoint." />
      </Panel>

      <Panel
        title="Runtime Settings"
        actions={(
          <SupportActionMenu
            items={[
              {
                id: 'copy-state-dir-runtime',
                label: 'Copy state dir',
                description: 'Copy the backend state directory from runtime settings.',
                disabled: !runtimeSettings?.state_dir,
                onSelect: () => copyValue('State dir', runtimeSettings?.state_dir || ''),
              },
              {
                id: 'copy-runtime-base',
                label: 'Copy model base',
                description: 'Copy the resolved Ollama base URL.',
                disabled: !runtimeSettings?.ollama_base_url,
                onSelect: () => copyValue('Model base', runtimeSettings?.ollama_base_url || ''),
              },
              {
                id: 'raw-runtime',
                label: 'View raw runtime',
                description: 'Inspect the full runtime settings object.',
                disabled: !runtimeSettings,
                onSelect: () => openJson('Runtime settings payload', runtimeSettings || {}, {
                  description: 'Raw runtime settings returned by /api/settings.',
                }),
              },
            ]}
          />
        )}
      >
        <dl className="settings-list">
          <div><dt>State dir</dt><dd>{runtimeSettings?.state_dir || 'unknown'}</dd></div>
          <div><dt>Nmap</dt><dd>{runtimeSettings?.nmap_path || runtimeSettings?.nmap_bin || 'not found'}</dd></div>
          <div><dt>Scan timeout</dt><dd>{runtimeSettings?.scan_timeout_seconds || 'unknown'}s</dd></div>
          <div><dt>Action timeout</dt><dd>{runtimeSettings?.action_timeout_seconds || 'unknown'}s</dd></div>
          <div><dt>Model base</dt><dd>{runtimeSettings?.ollama_base_url || 'not configured'}</dd></div>
        </dl>
        <SupportWhy title="Ask why" body="These values come directly from backend runtime configuration. They explain where state is written, which binaries are used, and which timeouts and model endpoint will shape future actions." />
      </Panel>

      <Panel title="Interface">
        <label>
          Refresh interval
          <select value={uiSettings.refreshSeconds} onChange={(event) => updateSetting('refreshSeconds', Number(event.target.value))}>
            <option value={2}>2 seconds</option>
            <option value={4}>4 seconds</option>
            <option value={8}>8 seconds</option>
            <option value={15}>15 seconds</option>
          </select>
        </label>
        <label>
          Mission chart mode
          <select value={uiSettings.chartMode} onChange={(event) => updateSetting('chartMode', event.target.value)}>
            <option value="counts">Counts</option>
            <option value="severity">Severity weighted</option>
          </select>
        </label>
        <label className="checkbox-line">
          <input type="checkbox" checked={uiSettings.autoSelectLatest} onChange={(event) => updateSetting('autoSelectLatest', event.target.checked)} />
          Auto-select latest target
        </label>
        <SupportWhy title="Ask why" body="These preferences are local browser UI settings. They affect polling cadence, chart weighting, and how aggressively the dashboard follows the newest target, but they do not change backend behavior." />
      </Panel>

      <Panel
        title="Diagnostics"
        actions={(
          <SupportActionMenu
            items={[
              {
                id: 'raw-ollama',
                label: 'View raw diagnostics',
                description: 'Inspect only the Ollama probe payload.',
                disabled: !diagnostics?.ollama,
                onSelect: () => openJson('Ollama diagnostics', diagnostics?.ollama || {}, {
                  description: 'This is the raw model diagnostics object returned from /api/settings.',
                }),
              },
              {
                id: 'copy-ollama-base',
                label: 'Copy model base',
                description: 'Copy the current Ollama base URL.',
                disabled: !ollamaBase,
                onSelect: () => copyValue('Model base', ollamaBase || ''),
              },
              {
                id: 'open-ollama-panel',
                label: 'Open Ollama in browser',
                description: 'Open the current Ollama base URL in a new tab.',
                disabled: !ollamaBase,
                onSelect: () => openUrl('Ollama', ollamaBase),
              },
            ]}
          />
        )}
      >
        <div className="settings-list">
          <div><dt>Configured</dt><dd>{diagnostics?.ollama?.configured ? 'yes' : 'no'}</dd></div>
          <div><dt>Reachable</dt><dd>{diagnostics?.ollama?.reachable ? 'yes' : 'no'}</dd></div>
          <div><dt>Model count</dt><dd>{diagnostics?.ollama?.models?.length || 0}</dd></div>
          <div><dt>Last error</dt><dd>{cleanDisplayText(diagnostics?.ollama?.error, 'none')}</dd></div>
        </div>
        <SupportWhy
          title="Ask why"
          body={diagnostics?.ollama?.reachable
            ? `Diagnostics are healthy because the backend successfully reached ${ollamaBase || 'the configured model base'} and enumerated ${diagnostics.ollama.models?.length || 0} models.`
            : `Diagnostics are degraded because the backend probe could not complete against ${ollamaBase || 'the configured model base'}. Review the raw payload for the exact probe error.`}
        />
      </Panel>

      <Panel
        title="LLM Prompts"
        className="wide"
        actions={(
          <SupportActionMenu
            items={[
              {
                id: 'copy-prompt-log',
                label: 'Copy prompt log path',
                description: 'Copy the on-disk JSONL path for prompt history.',
                disabled: !llmPrompts?.prompt_log_path,
                onSelect: () => copyValue('Prompt log path', llmPrompts?.prompt_log_path || ''),
              },
              {
                id: 'raw-prompt-history',
                label: 'View raw prompt history',
                description: 'Inspect the raw prompt-history payload.',
                disabled: !llmPrompts,
                onSelect: () => openJson('Prompt history payload', llmPrompts || {}, {
                  description: 'This is the raw /api/llm/prompts payload currently backing the prompt view.',
                }),
              },
            ]}
          />
        )}
      >
        <div className="prompt-stack">
          <SupportCard
            title="System prompt"
            subtitle="Standing rules applied to each mission-control LLM request."
            menuItems={[
              {
                id: 'copy-system-prompt',
                label: 'Copy prompt',
                description: 'Copy the current system prompt.',
                disabled: !llmPrompts?.system_prompt,
                onSelect: () => copyValue('System prompt', llmPrompts?.system_prompt || ''),
              },
              {
                id: 'view-system-prompt',
                label: 'View raw prompt',
                description: 'Open the full system prompt in a modal.',
                disabled: !llmPrompts?.system_prompt,
                onSelect: () => openText('System prompt', llmPrompts?.system_prompt || '', {
                  description: 'Exact system text prepended to LLM interactions.',
                }),
              },
            ]}
          >
            <pre>{llmPrompts?.system_prompt || 'Prompt data has not loaded yet.'}</pre>
            <SupportWhy title="Ask why" body={templateWhy('system')} />
          </SupportCard>

          <SupportCard
            title="User prompt template"
            subtitle="How operator requests are expanded into full model inputs."
            menuItems={[
              {
                id: 'copy-user-template',
                label: 'Copy prompt',
                description: 'Copy the current user prompt template.',
                disabled: !llmPrompts?.user_prompt_template,
                onSelect: () => copyValue('User prompt template', llmPrompts?.user_prompt_template || ''),
              },
              {
                id: 'view-user-template',
                label: 'View raw prompt',
                description: 'Open the template in a modal.',
                disabled: !llmPrompts?.user_prompt_template,
                onSelect: () => openText('User prompt template', llmPrompts?.user_prompt_template || '', {
                  description: 'Exact template used to build the stored user prompt text.',
                }),
              },
            ]}
          >
            <pre>{llmPrompts?.user_prompt_template || 'Prompt data has not loaded yet.'}</pre>
            <SupportWhy title="Ask why" body={templateWhy('template')} />
          </SupportCard>

          <SupportCard
            title="Recent prompt log"
            subtitle={llmPrompts?.prompt_log_path || 'No prompt log path available.'}
            menuItems={[
              {
                id: 'copy-log-path-inline',
                label: 'Copy prompt log path',
                description: 'Copy the JSONL prompt history path.',
                disabled: !llmPrompts?.prompt_log_path,
                onSelect: () => copyValue('Prompt log path', llmPrompts?.prompt_log_path || ''),
              },
              {
                id: 'view-log-raw',
                label: 'View raw prompt history',
                description: 'Open the full recent-prompt array.',
                disabled: !llmPrompts?.recent_prompts?.length,
                onSelect: () => openJson('Recent prompt history', llmPrompts?.recent_prompts || [], {
                  description: 'Recent prompt entries as returned by /api/llm/prompts.',
                }),
              },
            ]}
          >
            <SupportWhy title="Ask why" body="Prompt history is written to a JSONL log so operators can audit exact LLM inputs after the fact, including the expanded prompt text and the original operator request." />
          </SupportCard>

          {promptHistory.length ? (
            <div className="prompt-history">
              {promptHistory.map((prompt) => (
                <SupportCard
                  key={prompt.id}
                  meta={formatDateTime(prompt.timestamp_utc)}
                  title={cleanDisplayText(`${prompt.ip_address} · ${prompt.model}`, 'prompt')}
                  subtitle={prompt.operator_prompt || 'No operator prompt stored.'}
                  menuItems={[
                    {
                      id: `copy-operator-${prompt.id}`,
                      label: 'Copy operator prompt',
                      description: 'Copy only the original operator request.',
                      disabled: !prompt.operator_prompt,
                      onSelect: () => copyValue('Operator prompt', prompt.operator_prompt || ''),
                    },
                    {
                      id: `view-raw-${prompt.id}`,
                      label: 'View raw prompt',
                      description: 'Open the full recorded prompt entry.',
                      onSelect: () => openJson(`Prompt entry ${prompt.id}`, prompt, {
                        description: 'Exact stored prompt record from the prompt-history log.',
                      }),
                    },
                    {
                      id: `copy-full-${prompt.id}`,
                      label: 'Copy full prompt',
                      description: 'Copy the final user prompt sent to the model.',
                      disabled: !prompt.user_prompt,
                      onSelect: () => copyValue('Full user prompt', prompt.user_prompt || ''),
                    },
                  ]}
                >
                  <pre>{prompt.user_prompt}</pre>
                  <SupportWhy title="Ask why" body={promptWhy(prompt, llmPrompts)} />
                </SupportCard>
              ))}
            </div>
          ) : <EmptyState title="No recorded prompts" body="Prompt history will appear after an LLM interaction is requested." />}
        </div>
        <SupportModal modal={modal} onClose={closeModal} />
      </Panel>
    </div>
  )
}
