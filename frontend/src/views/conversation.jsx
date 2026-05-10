import React from 'react'
import { badgeClass, buildExecutionItems, cleanDisplayText, executionKey, firstHttpUrl, stageLabel, summarizeContextCounts } from '../lib/app-utils'
import { EmptyState, Panel } from '../components/primitives'
import { ActionBar, ActionDialog, ActionMenu, ActionNotice, buildWhySections, useActionRuntime } from './dashboard-actions'
import { ApprovalsPanel } from './approvals'
import { JobsPanel } from './jobs'

export function ConversationView({
  activeTarget,
  backendHealth,
  approvalQueue,
  loading,
  decideAction,
  removeAction,
  stopExecution,
  selectedExecutionKey,
  setSelectedExecutionKey,
  sendPrompt,
  promptDraft,
  setPromptDraft,
  promptModel,
  setPromptModel,
  conversationContext,
  setConversationContext,
  contextForm,
  setContextForm,
  addContextBlock,
  removeContextBlock,
}) {
  const actionRuntime = useActionRuntime()
  const services = activeTarget?.services || []
  const findings = activeTarget?.findings || []
  const observations = activeTarget?.observations || []
  const contextBlocks = activeTarget?.context_blocks || []
  const conversation = activeTarget?.conversation || []
  const actions = activeTarget?.agent_actions || []
  const actionById = Object.fromEntries(actions.map((item) => [item.id, item]))
  const executionItems = buildExecutionItems(activeTarget)
  const latestMessage = conversation[conversation.length - 1] || null
  const selectedBlockCount = conversationContext.blockIds.length
  const promptPresets = [
    {
      id: 'continue',
      label: 'Continue HTB Flow',
      prompt: 'Continue autonomously using the HTB methodology. Move from the current evidence to the next smallest useful step, explain the mindset shift, and keep terminal actions approval-gated.',
    },
    {
      id: 'web',
      label: 'Web Mindset',
      prompt: 'Shift into web-enumeration mode. Validate the exposed web surfaces, follow any strong content clues, and only suggest focused directory discovery if the quieter checks are exhausted.',
    },
    {
      id: 'creds',
      label: 'Default Creds',
      prompt: 'Shift into authentication-check mode. Test only high-probability anonymous access or default credentials supported by the current services and observations, and keep it approval-gated.',
    },
  ]

  function updateContextField(key, value) {
    setConversationContext((current) => ({ ...current, [key]: value }))
  }

  function updateContextForm(key, value) {
    setContextForm((current) => ({ ...current, [key]: value }))
  }

  function toggleContextBlock(blockId) {
    setConversationContext((current) => ({
      ...current,
      blockIds: current.blockIds.includes(blockId)
        ? current.blockIds.filter((item) => item !== blockId)
        : [...current.blockIds, blockId],
    }))
  }

  const attachedCounts = {
    services: conversationContext.includeServices ? services.length : 0,
    findings: conversationContext.includeFindings ? findings.length : 0,
    observations: conversationContext.includeObservations ? observations.length : 0,
    pending_actions: conversationContext.includePendingActions ? approvalQueue.length : 0,
    timeline: conversationContext.includeTimeline ? (activeTarget?.timeline || []).length : 0,
    context_blocks: selectedBlockCount,
  }

  return (
    <>
      <div className="conversation-grid">
        <section className="conversation-stack">
          <Panel title="Conversation Actions" meta={activeTarget.display_name || activeTarget.ip_address} className="wide">
            <ActionBar>
              <button type="button" onClick={() => actionRuntime.showText(
                'Why this conversation page matters',
                buildWhySections([
                  { label: 'Purpose', value: 'Conversation combines structured target context, saved long-form notes, and approval-gated assistant actions in one operator loop.' },
                  { label: 'Attached context', value: summarizeContextCounts(attachedCounts) },
                  { label: 'Transcript size', value: `${conversation.length} turn(s) and ${contextBlocks.length} saved block(s) are currently available to the assistant.` },
                ]),
              )}>Ask why</button>
              <button type="button" onClick={() => actionRuntime.showJson('Raw conversation state', { conversation, contextBlocks, attachedCounts, latestMessage })}>View raw input</button>
              <button type="button" onClick={() => actionRuntime.showText('Latest assistant output', latestMessage?.content || 'No assistant response is available yet.')}>View raw output</button>
              <button type="button" onClick={() => actionRuntime.copyJson('Conversation transcript JSON', conversation)}>Copy transcript JSON</button>
              <button type="button" onClick={() => actionRuntime.jump('Approvals')}>Jump to approvals</button>
              <button type="button" onClick={() => actionRuntime.jump('Jobs')}>Jump to jobs</button>
            </ActionBar>
          </Panel>

          <article className="conversation-hero panel">
            <div>
              <span className="eyebrow">Target-linked Assistant</span>
              <h2>{activeTarget.display_name || activeTarget.ip_address}</h2>
              <p>{cleanDisplayText(activeTarget.latest_summary, 'Attach target context and ask the model to reason or queue next steps.')}</p>
            </div>
            <div className="hero-meta">
              <span className={badgeClass(activeTarget.phase)}>{activeTarget.phase}</span>
              <span className={badgeClass(backendHealth?.ollama?.reachable ? 'ready' : 'blocked')}>
                {backendHealth?.ollama?.reachable ? 'model online' : 'heuristic mode'}
              </span>
              <ActionMenu
                compact
                actions={[
                  {
                    label: 'Ask why',
                    onSelect: () => actionRuntime.showText(
                      'Why this target is linked to chat',
                      buildWhySections([
                        { label: 'Active target', value: activeTarget.display_name || activeTarget.ip_address },
                        { label: 'Phase', value: activeTarget.phase || 'unknown' },
                        { label: 'Summary', value: activeTarget.latest_summary || 'No summary recorded.' },
                      ]),
                    ),
                  },
                  {
                    label: 'Copy target JSON',
                    onSelect: () => actionRuntime.copyJson('Target JSON', activeTarget),
                  },
                  {
                    label: 'View raw target',
                    onSelect: () => actionRuntime.showJson('Raw target JSON', activeTarget),
                  },
                ]}
              />
            </div>
          </article>

          <Panel
            title="Context Matrix"
            meta={`${services.length} svc · ${findings.length} findings`}
            actions={(
              <ActionMenu
                label="Panel Actions"
                actions={[
                  {
                    label: 'Ask why',
                    onSelect: () => actionRuntime.showText(
                      'Why the context matrix exists',
                      buildWhySections([
                        { label: 'Purpose', value: 'These toggles control which live evidence is serialized into the next assistant prompt.' },
                        { label: 'Current attachment', value: summarizeContextCounts(attachedCounts) },
                      ]),
                    ),
                  },
                  {
                    label: 'View raw context',
                    onSelect: () => actionRuntime.showJson('Conversation context flags', conversationContext),
                  },
                  {
                    label: 'Copy context flags',
                    onSelect: () => actionRuntime.copyJson('Conversation context flags', conversationContext),
                  },
                ]}
              />
            )}
          >
          <div className="context-matrix">
            <label className="context-toggle">
              <input type="checkbox" checked={conversationContext.includeServices} onChange={(event) => updateContextField('includeServices', event.target.checked)} />
              <span>Ports & versions</span>
            </label>
            <label className="context-toggle">
              <input type="checkbox" checked={conversationContext.includeFindings} onChange={(event) => updateContextField('includeFindings', event.target.checked)} />
              <span>Parsed findings</span>
            </label>
            <label className="context-toggle">
              <input type="checkbox" checked={conversationContext.includeObservations} onChange={(event) => updateContextField('includeObservations', event.target.checked)} />
              <span>Previous results</span>
            </label>
            <label className="context-toggle">
              <input type="checkbox" checked={conversationContext.includePendingActions} onChange={(event) => updateContextField('includePendingActions', event.target.checked)} />
              <span>Approval queue</span>
            </label>
            <label className="context-toggle">
              <input type="checkbox" checked={conversationContext.includeTimeline} onChange={(event) => updateContextField('includeTimeline', event.target.checked)} />
              <span>Recent timeline</span>
            </label>
          </div>
          <div className="context-preview">
            <article>
              <strong>Live Context</strong>
              <span>{summarizeContextCounts(attachedCounts)}</span>
            </article>
            <article>
              <strong>Model Surface</strong>
              <span>{backendHealth?.ollama?.reachable ? backendHealth?.ollama?.base_url || 'remote model configured' : 'local evidence-only fallback available'}</span>
            </article>
          </div>
          </Panel>

          <Panel
            title="Context Vault"
            meta={contextBlocks.length}
            actions={contextBlocks.length ? (
              <ActionMenu
                label="Vault Actions"
                actions={[
                  {
                    label: 'View raw blocks',
                    onSelect: () => actionRuntime.showJson('Saved context blocks', contextBlocks),
                  },
                  {
                    label: 'Copy selected block ids',
                    onSelect: () => actionRuntime.copyText('Selected block IDs', conversationContext.blockIds.join('\n') || 'No blocks selected.'),
                  },
                ]}
              />
            ) : null}
          >
          <div className="context-block-list">
            {contextBlocks.map((block) => (
              <article key={block.id} className={conversationContext.blockIds.includes(block.id) ? 'context-block selected' : 'context-block'}>
                <label>
                  <input type="checkbox" checked={conversationContext.blockIds.includes(block.id)} onChange={() => toggleContextBlock(block.id)} />
                  <div>
                    <strong>{cleanDisplayText(block.title, 'Context block')}</strong>
                    <span>{block.kind} · {block.word_count || 0} words</span>
                    <p>{cleanDisplayText(block.content, 'No content')}</p>
                  </div>
                </label>
                <div style={{ display: 'flex', gap: '0.45rem', alignItems: 'center' }}>
                  <ActionMenu
                    compact
                    actions={[
                      {
                        label: 'Ask why',
                        onSelect: () => actionRuntime.showText(
                          `Why keep ${cleanDisplayText(block.title, 'this block')}`,
                          buildWhySections([
                            { label: 'Type', value: block.kind || 'notes' },
                            { label: 'Word count', value: `${block.word_count || 0}` },
                            { label: 'Content', value: block.content || 'No content stored.' },
                          ]),
                        ),
                      },
                      {
                        label: 'Copy block',
                        onSelect: () => actionRuntime.copyText('Context block', block.content || ''),
                      },
                      {
                        label: 'View raw block',
                        onSelect: () => actionRuntime.showJson('Context block', block),
                      },
                    ]}
                  />
                  <button type="button" onClick={() => removeContextBlock(block.id)} disabled={loading}>Delete</button>
                </div>
              </article>
            ))}
            {!contextBlocks.length ? <EmptyState title="No saved blocks" body="Save long-form notes, manual findings, credentials, or hypotheses here, then attach them to prompts." /> : null}
          </div>

          <form className="context-editor" onSubmit={addContextBlock}>
            <label>
              Block title
              <input value={contextForm.title} onChange={(event) => updateContextForm('title', event.target.value)} placeholder="TWiki routes, Tomcat banner, and prior curl results" required />
            </label>
            <label>
              Type
              <select value={contextForm.kind} onChange={(event) => updateContextForm('kind', event.target.value)}>
                <option value="notes">Notes</option>
                <option value="service-map">Service Map</option>
                <option value="results">Results</option>
                <option value="credentials">Credentials</option>
                <option value="hypothesis">Hypothesis</option>
              </select>
            </label>
            <label className="full-width">
              Long-form context
              <textarea value={contextForm.content} onChange={(event) => updateContextForm('content', event.target.value)} rows={6} placeholder="Paste large blocks of target context, versions, hostnames, actions tried, raw output summaries, or reasoning you want attached." required />
            </label>
            <button className="primary" type="submit" disabled={loading}>{loading ? 'Saving...' : 'Save Context Block'}</button>
          </form>
          </Panel>
        </section>

        <section className="conversation-transcript panel">
        <div className="panel-head">
          <h3>Transcript</h3>
          <div className="panel-head-meta">
            <span>{conversation.length} turns</span>
            <span>{selectedBlockCount} saved blocks attached</span>
          </div>
        </div>

        <div className="transcript-stream">
          {conversation.map((message) => {
            const linkedActions = (message.queued_action_ids || []).map((id) => actionById[id]).filter(Boolean)
            return (
              <article className={`message-card role-${message.role}`} key={message.id}>
                <div className="message-meta">
                  <strong>{message.role === 'user' ? 'Operator' : 'Assistant'}</strong>
                  <span>{message.model || 'mission-control'}</span>
                  <small>{message.created_at}</small>
                </div>
                <pre>{cleanDisplayText(message.content, 'No content')}</pre>
                {message.context_snapshot?.attached ? <span className="message-context">{summarizeContextCounts(message.context_snapshot.attached)}</span> : null}
                <ActionMenu
                  compact
                  actions={[
                    {
                      label: 'Ask why',
                      onSelect: () => actionRuntime.showText(
                        `Why this ${message.role} turn matters`,
                        buildWhySections([
                          { label: 'Role', value: message.role || 'unknown' },
                          { label: 'Model', value: message.model || 'mission-control' },
                          { label: 'Message', value: message.content || 'No content recorded.' },
                        ]),
                      ),
                    },
                    {
                      label: 'Copy message',
                      onSelect: () => actionRuntime.copyText('Message content', message.content || ''),
                    },
                    {
                      label: 'View raw message',
                      onSelect: () => actionRuntime.showJson('Conversation message', message),
                    },
                  ]}
                />
                {linkedActions.length ? (
                  <div className="message-actions">
                    {linkedActions.map((action) => (
                      <article key={action.id}>
                        <div>
                          <strong>{cleanDisplayText(action.label, 'Queued action')}</strong>
                          <span>{cleanDisplayText(action.reason, 'No reason provided.')}</span>
                          <div className="approval-stage-row">
                            <span className="stage-chip">{stageLabel(action.stage)}</span>
                            <span className="stage-chip muted">{action.source === 'operator_prompt' ? 'operator requested' : 'playbook queued'}</span>
                          </div>
                          {action.mindset ? <small className="approval-mindset">{cleanDisplayText(action.mindset, '')}</small> : null}
                          <code>{action.command}</code>
                        </div>
                        <div className="approval-actions">
                          <span className={badgeClass(action.status)}>{action.status}</span>
                          <button className="primary" type="button" disabled={loading || !action.tool_available || action.status !== 'pending_approval'} onClick={() => decideAction(action.id, 'approve')}>Approve</button>
                          <button className="deny" type="button" disabled={loading || !['pending_approval', 'blocked'].includes(action.status)} onClick={() => decideAction(action.id, 'deny')}>Deny</button>
                          <button type="button" disabled={loading} onClick={() => removeAction(action.id)}>Remove</button>
                        </div>
                      </article>
                    ))}
                  </div>
                ) : null}
              </article>
            )
          })}
          {!conversation.length ? <EmptyState title="No chat yet" body="Ask a question about the target or tell the assistant to queue a terminal action for approval." /> : null}
        </div>

          <form className="chat-composer" onSubmit={sendPrompt}>
          <div className="composer-head">
            <div>
              <strong>Operator Prompt</strong>
              <span>{latestMessage?.role === 'assistant' ? 'The last assistant turn can queue new approval cards directly into the mission flow.' : 'Ask a question or request the next action.'}</span>
            </div>
            <label>
              Model
              <select value={promptModel} onChange={(event) => setPromptModel(event.target.value)}>
                <option value="auto">Auto</option>
                <option value="local-heuristic">Heuristic only</option>
              </select>
            </label>
          </div>
          <div className="prompt-presets">
            {promptPresets.map((preset) => (
              <button key={preset.id} type="button" onClick={() => setPromptDraft(preset.prompt)}>
                {preset.label}
              </button>
            ))}
          </div>
          <textarea value={promptDraft} onChange={(event) => setPromptDraft(event.target.value)} rows={6} placeholder="Example: Continue autonomously using the HTB methodology and queue the next approval-gated step. Or: Shift into web-enumeration mode and justify whether ffuf or default-creds testing is warranted." required />
          <div className="composer-foot">
            <span>{summarizeContextCounts(attachedCounts)}</span>
            <ActionMenu
              compact
              actions={[
                {
                  label: 'Ask why',
                  onSelect: () => actionRuntime.showText(
                    'Why this prompt payload will be sent',
                    buildWhySections([
                      { label: 'Draft', value: promptDraft || 'No draft entered yet.' },
                      { label: 'Selected model', value: promptModel || 'auto' },
                      { label: 'Attached context', value: summarizeContextCounts(attachedCounts) },
                    ]),
                  ),
                },
                {
                  label: 'View raw prompt',
                  onSelect: () => actionRuntime.showText('Raw operator prompt', promptDraft || 'No prompt drafted yet.'),
                },
                {
                  label: 'Copy prompt',
                  onSelect: () => actionRuntime.copyText('Operator prompt', promptDraft || ''),
                },
              ]}
            />
            <button className="primary" type="submit" disabled={loading || !promptDraft.trim()}>{loading ? 'Thinking...' : 'Send To Assistant'}</button>
          </div>
          </form>
        </section>

        <section className="conversation-rail">
          <ApprovalsPanel approvalQueue={approvalQueue} loading={loading} decideAction={decideAction} removeAction={removeAction} />
          <JobsPanel activeTarget={activeTarget} selectedExecutionKey={selectedExecutionKey} setSelectedExecutionKey={setSelectedExecutionKey} stopExecution={stopExecution} loading={loading} condensed />
          <Panel
            title="Target Snapshot"
            meta={activeTarget.ip_address}
            actions={services.length ? (
              <ActionMenu
                label="Snapshot Actions"
                actions={[
                  {
                    label: 'View raw services',
                    onSelect: () => actionRuntime.showJson('Snapshot services', services),
                  },
                  {
                    label: 'Copy services JSON',
                    onSelect: () => actionRuntime.copyJson('Snapshot services JSON', services),
                  },
                ]}
              />
            ) : null}
          >
          <div className="snapshot-list">
            {services.slice(0, 6).map((service) => (
              <article key={`${service.protocol}-${service.port}`}>
                <strong>{service.port}/{service.protocol}</strong>
                <span>{cleanDisplayText(service.service, 'unknown')} · {cleanDisplayText(service.detail, 'no version detail')}</span>
                <ActionMenu
                  compact
                  actions={[
                    {
                      label: 'Ask why',
                      onSelect: () => actionRuntime.showText(
                        `Why ${cleanDisplayText(service.service, 'this service')} is in snapshot`,
                        buildWhySections([
                          { label: 'Exposure', value: `${service.protocol}/${service.port} is open on ${activeTarget.ip_address}.` },
                          { label: 'Version', value: service.detail || 'No version detail captured.' },
                        ]),
                      ),
                    },
                    {
                      label: 'Open in browser',
                      disabled: !firstHttpUrl(service, activeTarget.ip_address),
                      onSelect: () => actionRuntime.openBrowser(firstHttpUrl(service, activeTarget.ip_address)),
                    },
                    {
                      label: 'View raw service',
                      onSelect: () => actionRuntime.showJson('Snapshot service', service),
                    },
                  ]}
                />
              </article>
            ))}
            {!services.length ? <EmptyState title="No services yet" body="Run or finish enumeration to make chat context richer." /> : null}
          </div>
          </Panel>
        </section>
      </div>

      <ActionDialog dialog={actionRuntime.dialog} onClose={actionRuntime.closeDialog} />
      <ActionNotice notice={actionRuntime.notice} />
    </>
  )
}
