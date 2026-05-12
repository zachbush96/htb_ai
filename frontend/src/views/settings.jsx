import React, { useEffect, useState } from 'react'
import { DEFAULT_COMMAND_ALLOWLIST, cleanDisplayText, formatDateTime, normalizeCommandAllowlist } from '../lib/app-utils'
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

export function SettingsView({ apiBase, setApiBase, uiSettings, setUiSettings, runtimeSettings, diagnostics, modelCatalog, refreshModelCatalog, testSettings, llmPrompts, llmPlanner, updateLlmSettings, setPlannerEnabled, loading }) {
  const { notice, modal, closeModal, copyValue, openText, openJson, openUrl } = useSupportActions()
  const [llmForm, setLlmForm] = useState(() => runtimeSettings?.llm || {})
  const [commandDraft, setCommandDraft] = useState('')

  useEffect(() => {
    setLlmForm(runtimeSettings?.llm || {})
  }, [runtimeSettings?.llm])

  function updateSetting(key, value) {
    setUiSettings((current) => ({ ...current, [key]: value }))
  }

  const ollamaBase = diagnostics?.ollama?.base_url || runtimeSettings?.ollama_base_url || null
  const promptHistory = llmPrompts?.recent_prompts?.slice().reverse() || []
  const commandAllowlist = normalizeCommandAllowlist(uiSettings.commandAllowlist || DEFAULT_COMMAND_ALLOWLIST)
  const discoveredModels = Array.isArray(modelCatalog?.models) ? modelCatalog.models : []
  const currentModel = llmForm.default_model || 'auto'
  const modelOptions = [...new Set(['auto', ...discoveredModels, currentModel].filter(Boolean))]

  function updateLlmForm(key, value) {
    setLlmForm((current) => ({ ...current, [key]: value }))
  }

  function saveLlmSettings(event) {
    event.preventDefault()
    updateLlmSettings({
      ollama_base_url: llmForm.ollama_base_url || null,
      ollama_tailscale_host: llmForm.ollama_tailscale_host || null,
      ollama_timeout_seconds: Number(llmForm.ollama_timeout_seconds || 5),
      default_model: llmForm.default_model || 'auto',
      temperature: Number(llmForm.temperature ?? 0.2),
      num_ctx: Number(llmForm.num_ctx || 8192),
      autoplan_enabled: Boolean(llmForm.autoplan_enabled),
      autoplan_interval_seconds: Number(llmForm.autoplan_interval_seconds || 20),
      autoplan_max_actions_per_turn: Number(llmForm.autoplan_max_actions_per_turn || 4),
      autoplan_include_timeline: Boolean(llmForm.autoplan_include_timeline),
      autoplan_include_execution_history: Boolean(llmForm.autoplan_include_execution_history),
      autoplan_prompt: llmForm.autoplan_prompt || '',
      system_prompt: llmForm.system_prompt || null,
    })
  }

  function addAllowedCommand(event) {
    event.preventDefault()
    const next = normalizeCommandAllowlist([...commandAllowlist, commandDraft])
    if (next.length !== commandAllowlist.length) {
      updateSetting('commandAllowlist', next)
    }
    setCommandDraft('')
  }

  function removeAllowedCommand(commandName) {
    updateSetting('commandAllowlist', commandAllowlist.filter((item) => item !== commandName))
  }

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
        title="Command Allowlist"
        className="wide"
        actions={(
          <SupportActionMenu
            items={[
              {
                id: 'copy-command-allowlist',
                label: 'Copy allowlist',
                description: 'Copy the current command allowlist as JSON.',
                onSelect: () => copyValue('Command allowlist', JSON.stringify(commandAllowlist, null, 2)),
              },
              {
                id: 'raw-command-allowlist',
                label: 'View raw allowlist',
                description: 'Inspect the persisted backend allowlist and defaults.',
                onSelect: () => openJson('Command allowlist', { commandAllowlist, defaults: DEFAULT_COMMAND_ALLOWLIST }, {
                  description: 'These names are stored in backend runtime settings and can auto-run matching non-install commands.',
                }),
              },
            ]}
          />
        )}
      >
        <form className="allowlist-editor" onSubmit={addAllowedCommand}>
          <label>
            Command name
            <input value={commandDraft} onChange={(event) => setCommandDraft(event.target.value)} placeholder="curl" />
          </label>
          <button className="primary" type="submit" disabled={!normalizeCommandAllowlist([commandDraft]).length}>Add Command</button>
          <button type="button" onClick={() => updateSetting('commandAllowlist', DEFAULT_COMMAND_ALLOWLIST)}>Restore Defaults</button>
        </form>
        <div className="allowlist-chip-grid">
          {commandAllowlist.map((commandName) => (
            <span className="allowlist-chip" key={commandName}>
              <span>{commandName}</span>
              <em>auto-allowed/default</em>
              <button type="button" aria-label={`Remove ${commandName}`} onClick={() => removeAllowedCommand(commandName)}>Remove</button>
            </span>
          ))}
        </div>
        <SupportWhy title="Ask why" body="The allowlist is persisted by the backend for routine command names. Matching non-install commands can auto-run, missing binaries still report command-not-found output, and software installation remains approval-gated." />
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
        title="LLM Usage"
        className="wide"
        actions={(
          <SupportActionMenu
            items={[
              {
                id: 'raw-llm-settings',
                label: 'View raw LLM settings',
                description: 'Inspect persisted LLM usage and planner configuration.',
                onSelect: () => openJson('LLM runtime settings', { settings: llmForm, model_catalog: modelCatalog, planner: llmPlanner }, {
                  description: 'Current settings returned from /api/settings plus planner status from /api/llm/planner.',
                }),
              },
              {
                id: 'refresh-model-catalog',
                label: 'Refresh models',
                description: 'Query the configured OpenAI-compatible /v1/models endpoint.',
                onSelect: refreshModelCatalog,
              },
              {
                id: 'toggle-planner',
                label: llmPlanner?.enabled ? 'Pause planner' : 'Start planner',
                description: 'Toggle the global autonomous planning loop.',
                onSelect: () => setPlannerEnabled(!llmPlanner?.enabled),
              },
            ]}
          />
        )}
      >
        <form className="settings-form-grid" onSubmit={saveLlmSettings}>
          <label>
            Ollama base URL
            <input value={llmForm.ollama_base_url || ''} onChange={(event) => updateLlmForm('ollama_base_url', event.target.value)} placeholder="http://127.0.0.1:11434" />
          </label>
          <label>
            Tailscale host
            <input value={llmForm.ollama_tailscale_host || ''} onChange={(event) => updateLlmForm('ollama_tailscale_host', event.target.value)} placeholder="100.102.78.116" />
          </label>
          <label>
            Default model
            <select value={currentModel} onChange={(event) => updateLlmForm('default_model', event.target.value)}>
              {modelOptions.map((modelName) => (
                <option key={modelName} value={modelName}>{modelName === 'auto' ? 'Auto' : modelName}</option>
              ))}
            </select>
          </label>
          <label>
            Timeout seconds
            <input type="number" min="1" max="180" value={llmForm.ollama_timeout_seconds || 5} onChange={(event) => updateLlmForm('ollama_timeout_seconds', event.target.value)} />
          </label>
          <label>
            Temperature
            <input type="number" min="0" max="2" step="0.1" value={llmForm.temperature ?? 0.2} onChange={(event) => updateLlmForm('temperature', event.target.value)} />
          </label>
          <label>
            Context window
            <input type="number" min="1024" max="65536" step="1024" value={llmForm.num_ctx || 8192} onChange={(event) => updateLlmForm('num_ctx', event.target.value)} />
          </label>
          <label>
            Planner interval
            <input type="number" min="5" max="3600" value={llmForm.autoplan_interval_seconds || 20} onChange={(event) => updateLlmForm('autoplan_interval_seconds', event.target.value)} />
          </label>
          <label>
            Max actions per turn
            <input type="number" min="1" max="10" value={llmForm.autoplan_max_actions_per_turn || 4} onChange={(event) => updateLlmForm('autoplan_max_actions_per_turn', event.target.value)} />
          </label>
          <label className="checkbox-line">
            <input type="checkbox" checked={Boolean(llmForm.autoplan_enabled)} onChange={(event) => updateLlmForm('autoplan_enabled', event.target.checked)} />
            Run autonomous planner loop
          </label>
          <label className="checkbox-line">
            <input type="checkbox" checked={Boolean(llmForm.autoplan_include_execution_history)} onChange={(event) => updateLlmForm('autoplan_include_execution_history', event.target.checked)} />
            Feed previous jobs/actions/results
          </label>
          <label className="checkbox-line">
            <input type="checkbox" checked={Boolean(llmForm.autoplan_include_timeline)} onChange={(event) => updateLlmForm('autoplan_include_timeline', event.target.checked)} />
            Include recent timeline
          </label>
          <label className="full-width">
            Planner prompt
            <textarea rows={4} value={llmForm.autoplan_prompt || ''} onChange={(event) => updateLlmForm('autoplan_prompt', event.target.value)} />
          </label>
          <label className="full-width">
            System prompt override
            <textarea rows={5} value={llmForm.system_prompt || ''} onChange={(event) => updateLlmForm('system_prompt', event.target.value)} placeholder="Leave blank to use the built-in HTB Mission Control system prompt." />
          </label>
          <div className="button-row full-width">
            <button className="primary" type="submit" disabled={loading}>{loading ? 'Saving...' : 'Save LLM Settings'}</button>
            <button type="button" disabled={loading} onClick={refreshModelCatalog}>Refresh Models</button>
            <button type="button" disabled={loading} onClick={() => setPlannerEnabled(!llmPlanner?.enabled)}>
              {llmPlanner?.enabled ? 'Pause Planner' : 'Start Planner'}
            </button>
          </div>
        </form>
        <dl className="settings-list">
          <div><dt>Loop</dt><dd>{llmPlanner?.enabled ? 'enabled' : 'paused'}</dd></div>
          <div><dt>Worker</dt><dd>{llmPlanner?.worker_alive ? 'running' : 'stopped'}</dd></div>
          <div><dt>Targets</dt><dd>{llmPlanner?.targets?.length || 0}</dd></div>
          <div><dt>Models</dt><dd>{modelCatalog?.reachable ? `${discoveredModels.length} from /v1/models` : cleanDisplayText(modelCatalog?.error, 'not loaded')}</dd></div>
          <div><dt>Planner log</dt><dd>{llmPlanner?.planner_log_path || 'not created yet'}</dd></div>
        </dl>
        <SupportWhy title="Ask why" body="These settings control which model endpoint Mission Control uses, how much context is sent, and whether the autonomous planner periodically feeds prior jobs, actions, and results back into the LLM to queue fresh approval-gated actions." />
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
