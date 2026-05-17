import React, { useEffect, useMemo, useState } from 'react'
import { createRoot } from 'react-dom/client'
import './styles.css'
import { buildExecutionItems, cleanSummaryText, commandAllowlistFromRuntime, executionIsActive, executionKey, findCredentialHints, inferDefaultApiBase, loadUiSettings, NAV_ITEMS, normalizeError, sortApprovalQueue } from './lib/app-utils'
import { ConversationView } from './views/conversation'
import { DashboardView } from './views/dashboard'
import { ProgressView } from './views/progress'
import { TargetsView } from './views/targets'
import { TimelinePanel } from './views/timeline'
import { ApprovalsPanel } from './views/approvals'
import { JobsPanel } from './views/jobs'
import { ShellView } from './views/shell'
import { LootView } from './views/loot'
import { CredentialsView } from './views/credentials'
import { ReportsView } from './views/reports'
import { TeamView } from './views/team'
import { SettingsView } from './views/settings'

function App() {
  const [apiBase, setApiBase] = useState(() => window.localStorage.getItem('htbmc-api-base') || inferDefaultApiBase())
  const [uiSettings, setUiSettings] = useState(loadUiSettings)
  const [activeView, setActiveView] = useState('conversation')
  const [targets, setTargets] = useState([])
  const [activeTargetId, setActiveTargetId] = useState(null)
  const [activeTarget, setActiveTarget] = useState(null)
  const [logs, setLogs] = useState([])
  const [targetIp, setTargetIp] = useState('')
  const [targetLabel, setTargetLabel] = useState('')
  const [backendHealth, setBackendHealth] = useState(null)
  const [runtimeSettings, setRuntimeSettings] = useState(null)
  const [diagnostics, setDiagnostics] = useState(null)
  const [modelCatalog, setModelCatalog] = useState(null)
  const [reports, setReports] = useState(null)
  const [targetReport, setTargetReport] = useState(null)
  const [toolCatalog, setToolCatalog] = useState(null)
  const [llmPrompts, setLlmPrompts] = useState(null)
  const [llmPlanner, setLlmPlanner] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [selectedExecutionKey, setSelectedExecutionKey] = useState(null)
  const [promptDraft, setPromptDraft] = useState('')
  const [promptModel, setPromptModel] = useState('auto')
  const [conversationContext, setConversationContext] = useState({
    includeServices: true,
    includeFindings: true,
    includeObservations: true,
    includePendingActions: true,
    includeTimeline: false,
    blockIds: [],
  })
  const [contextForm, setContextForm] = useState({
    title: '',
    kind: 'notes',
    content: '',
  })

  useEffect(() => {
    window.localStorage.setItem('htbmc-api-base', apiBase)
  }, [apiBase])

  useEffect(() => {
    window.localStorage.setItem('htbmc-ui-settings', JSON.stringify(uiSettings))
  }, [uiSettings])

  useEffect(() => {
    refreshEverything(activeTargetId)
    const interval = window.setInterval(() => {
      refreshEverything(activeTargetId)
    }, uiSettings.refreshSeconds * 1000)
    return () => window.clearInterval(interval)
  }, [apiBase, activeTargetId, uiSettings.refreshSeconds])

  async function request(path, options = {}) {
    const base = apiBase.endsWith('/') ? apiBase.slice(0, -1) : apiBase
    const response = await fetch(`${base}${path}`, {
      headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
      ...options,
    })
    const body = await response.text()
    const json = body ? JSON.parse(body) : null
    if (!response.ok) {
      throw new Error(json?.detail || json?.message || body || `Request failed with HTTP ${response.status}`)
    }
    return json
  }

  async function refreshModelCatalog() {
    try {
      const payload = await request('/api/settings/models')
      setModelCatalog(payload.model_catalog)
      return payload.model_catalog
    } catch (err) {
      const fallback = {
        configured: false,
        reachable: false,
        base_url: null,
        endpoint: null,
        models: [],
        error: normalizeError(err),
      }
      setModelCatalog(fallback)
      return fallback
    }
  }

  async function refreshEverything(preferredTargetId = activeTargetId) {
    try {
      const [health, targetList, settingsPayload, modelPayload, reportPayload, promptPayload, plannerPayload, toolPayload] = await Promise.all([
        request('/healthz'),
        request('/api/targets'),
        request('/api/settings'),
        request('/api/settings/models').catch((err) => ({
          model_catalog: {
            configured: false,
            reachable: false,
            base_url: null,
            endpoint: null,
            models: [],
            error: normalizeError(err),
          },
        })),
        request('/api/reports/overview'),
        request('/api/llm/prompts'),
        request('/api/llm/planner'),
        request('/api/tools/catalog'),
      ])
      setBackendHealth(health)
      setRuntimeSettings(settingsPayload.settings)
      setDiagnostics(settingsPayload)
      setModelCatalog(modelPayload.model_catalog)
      setReports(reportPayload)
      setLlmPrompts(promptPayload.prompts)
      setLlmPlanner(plannerPayload.planner)
      setToolCatalog(toolPayload)
      setTargets(targetList)
      const nextId = preferredTargetId && targetList.some((item) => item.id === preferredTargetId)
        ? preferredTargetId
        : uiSettings.autoSelectLatest ? targetList[0]?.id || null : activeTargetId
      setActiveTargetId(nextId)
      if (nextId) {
        const [detail, logPayload, reportDetail] = await Promise.all([
          request(`/api/targets/${nextId}`),
          request(`/api/targets/${nextId}/logs?limit=80`),
          request(`/api/targets/${nextId}/report`),
        ])
        setActiveTarget(detail)
        setLogs(logPayload.entries || [])
        setTargetReport(reportDetail.report)
      } else {
        setActiveTarget(null)
        setLogs([])
        setTargetReport(null)
      }
      setError('')
    } catch (err) {
      setError(normalizeError(err))
    }
  }

  async function testSettings() {
    setLoading(true)
    setError('')
    try {
      const payload = await request('/api/settings')
      setDiagnostics(payload)
      setRuntimeSettings(payload.settings)
      await refreshModelCatalog()
    } catch (err) {
      setError(normalizeError(err))
    } finally {
      setLoading(false)
    }
  }

  async function updateLlmSettings(nextSettings) {
    setLoading(true)
    setError('')
    try {
      const payload = await request('/api/settings/llm', {
        method: 'POST',
        body: JSON.stringify(nextSettings),
      })
      setDiagnostics(payload)
      setRuntimeSettings(payload.settings)
      setModelCatalog(payload.model_catalog)
      setLlmPlanner(payload.planner)
      await refreshEverything(activeTargetId)
    } catch (err) {
      setError(normalizeError(err))
    } finally {
      setLoading(false)
    }
  }

  async function setPlannerEnabled(enabled) {
    setLoading(true)
    setError('')
    try {
      const payload = await request(`/api/llm/planner/${enabled ? 'start' : 'stop'}`, { method: 'POST' })
      setRuntimeSettings(payload.settings)
      setLlmPlanner(payload.planner)
      await refreshEverything(activeTargetId)
    } catch (err) {
      setError(normalizeError(err))
    } finally {
      setLoading(false)
    }
  }

  async function runPlannerStep() {
    if (!activeTargetId) return
    setLoading(true)
    setError('')
    try {
      await request(`/api/targets/${activeTargetId}/planner/step`, { method: 'POST' })
      await refreshEverything(activeTargetId)
    } catch (err) {
      setError(normalizeError(err))
    } finally {
      setLoading(false)
    }
  }

  async function createAndStartTarget(event) {
    event.preventDefault()
    if (!targetIp.trim()) return
    setLoading(true)
    setError('')
    try {
      const result = await request('/api/targets/start', {
        method: 'POST',
        body: JSON.stringify({
          ip_address: targetIp.trim(),
          label: targetLabel.trim() || null,
        }),
      })
      setTargetIp('')
      setTargetLabel('')
      await refreshEverything(result.target?.id || null)
      setActiveView('conversation')
    } catch (err) {
      setError(normalizeError(err))
    } finally {
      setLoading(false)
    }
  }

  async function rerunEnumeration() {
    if (!activeTargetId) return
    setLoading(true)
    setError('')
    try {
      await request(`/api/targets/${activeTargetId}/enumeration/start`, { method: 'POST' })
      await refreshEverything(activeTargetId)
    } catch (err) {
      setError(normalizeError(err))
    } finally {
      setLoading(false)
    }
  }

  async function decideAction(actionId, decision) {
    if (!activeTargetId) return
    setLoading(true)
    setError('')
    try {
      await request(`/api/targets/${activeTargetId}/actions/${actionId}/${decision}`, {
        method: 'POST',
        body: JSON.stringify({ note: null }),
      })
      await refreshEverything(activeTargetId)
    } catch (err) {
      setError(normalizeError(err))
    } finally {
      setLoading(false)
    }
  }

  async function removeAction(actionId) {
    if (!activeTargetId) return
    setLoading(true)
    setError('')
    try {
      await request(`/api/targets/${activeTargetId}/actions/${actionId}`, {
        method: 'DELETE',
        body: JSON.stringify({ note: 'Removed from approval queue in UI' }),
      })
      await refreshEverything(activeTargetId)
    } catch (err) {
      setError(normalizeError(err))
    } finally {
      setLoading(false)
    }
  }

  async function deleteTarget(targetId, targetName) {
    const confirmed = window.confirm(`Remove target ${targetName} and all associated scans, logs, actions, and reports?`)
    if (!confirmed) return
    setLoading(true)
    setError('')
    try {
      await request(`/api/targets/${targetId}`, { method: 'DELETE' })
      const fallbackId = targetId === activeTargetId ? null : activeTargetId
      await refreshEverything(fallbackId)
      setActiveView('targets')
    } catch (err) {
      setError(normalizeError(err))
    } finally {
      setLoading(false)
    }
  }

  async function stopExecution(item) {
    if (!activeTargetId || !item) return
    setLoading(true)
    setError('')
    try {
      const suffix = item.execution_kind === 'job' ? 'jobs' : 'actions'
      await request(`/api/targets/${activeTargetId}/${suffix}/${item.id}/stop`, {
        method: 'POST',
        body: JSON.stringify({ note: 'Stopped from UI' }),
      })
      await refreshEverything(activeTargetId)
    } catch (err) {
      setError(normalizeError(err))
    } finally {
      setLoading(false)
    }
  }

  async function sendPrompt(event) {
    event.preventDefault()
    if (!activeTargetId || !activeTarget || !promptDraft.trim()) return
    setLoading(true)
    setError('')
    try {
      const payload = await request('/api/llm/interact', {
        method: 'POST',
        body: JSON.stringify({
          target_id: activeTargetId,
          ip_address: activeTarget.ip_address,
          prompt: promptDraft.trim(),
          model: promptModel,
          context_block_ids: conversationContext.blockIds,
          include_services: conversationContext.includeServices,
          include_findings: conversationContext.includeFindings,
          include_observations: conversationContext.includeObservations,
          include_pending_actions: conversationContext.includePendingActions,
          include_timeline: conversationContext.includeTimeline,
        }),
      })
      if (payload?.prompt_id) {
        setSelectedExecutionKey(`llm:${payload.prompt_id}`)
      }
      setPromptDraft('')
      await refreshEverything(activeTargetId)
      setActiveView('conversation')
    } catch (err) {
      setError(normalizeError(err))
    } finally {
      setLoading(false)
    }
  }

  async function addContextBlock(event) {
    event.preventDefault()
    if (!activeTargetId || !contextForm.title.trim() || !contextForm.content.trim()) return
    setLoading(true)
    setError('')
    try {
      await request(`/api/targets/${activeTargetId}/context`, {
        method: 'POST',
        body: JSON.stringify({
          title: contextForm.title.trim(),
          kind: contextForm.kind,
          content: contextForm.content.trim(),
        }),
      })
      setContextForm({ title: '', kind: 'notes', content: '' })
      await refreshEverything(activeTargetId)
    } catch (err) {
      setError(normalizeError(err))
    } finally {
      setLoading(false)
    }
  }

  async function removeContextBlock(contextBlockId) {
    if (!activeTargetId) return
    setLoading(true)
    setError('')
    try {
      await request(`/api/targets/${activeTargetId}/context/${contextBlockId}`, {
        method: 'DELETE',
      })
      setConversationContext((current) => ({
        ...current,
        blockIds: current.blockIds.filter((item) => item !== contextBlockId),
      }))
      await refreshEverything(activeTargetId)
    } catch (err) {
      setError(normalizeError(err))
    } finally {
      setLoading(false)
    }
  }

  async function setAutonomyProfile(profile) {
    if (!activeTargetId) return
    setLoading(true)
    setError('')
    try {
      await request(`/api/targets/${activeTargetId}/autonomy/profile`, {
        method: 'POST',
        body: JSON.stringify({ profile }),
      })
      await refreshEverything(activeTargetId)
    } catch (err) {
      setError(normalizeError(err))
    } finally {
      setLoading(false)
    }
  }

  async function pauseAutonomy() {
    if (!activeTargetId) return
    setLoading(true)
    setError('')
    try {
      await request(`/api/targets/${activeTargetId}/autonomy/pause`, { method: 'POST' })
      await refreshEverything(activeTargetId)
    } catch (err) {
      setError(normalizeError(err))
    } finally {
      setLoading(false)
    }
  }

  async function resumeAutonomy() {
    if (!activeTargetId) return
    setLoading(true)
    setError('')
    try {
      await request(`/api/targets/${activeTargetId}/autonomy/resume`, { method: 'POST' })
      await refreshEverything(activeTargetId)
    } catch (err) {
      setError(normalizeError(err))
    } finally {
      setLoading(false)
    }
  }

  const latestJob = activeTarget?.jobs?.[activeTarget.jobs.length - 1] || null
  const services = activeTarget?.services || []
  const findings = activeTarget?.findings || []
  const recommendations = activeTarget?.recommendations || []
  const actions = activeTarget?.agent_actions || []
  const observations = activeTarget?.observations || []
  const timeline = [...(activeTarget?.timeline || [])].reverse()
  const approvalQueue = sortApprovalQueue(actions.filter((item) => item.status === 'pending_approval' || item.status === 'blocked'))
  const commandAllowlist = commandAllowlistFromRuntime(runtimeSettings, uiSettings.commandAllowlist)
  const completedActions = actions.filter((item) => ['completed', 'failed', 'stopped'].includes(item.status))
  const runningJobs = (activeTarget?.jobs || []).filter((job) => ['running', 'queued', 'stopping'].includes(job.status))
  const executionItems = buildExecutionItems(activeTarget)
  const activeExecutionCount = executionItems.filter(executionIsActive).length
  const selectedExecution = executionItems.find((item) => executionKey(item) === selectedExecutionKey) || executionItems[0] || null
  const viewTitle = NAV_ITEMS.find((item) => item.id === activeView)?.label || 'Dashboard'
  const headerSummary = cleanSummaryText(activeTarget?.latest_summary, 'Mission status and target overview')

  useEffect(() => {
    if (!executionItems.length) {
      setSelectedExecutionKey(null)
      return
    }
    if (selectedExecutionKey && executionItems.some((item) => executionKey(item) === selectedExecutionKey)) return
    const activeExecution = executionItems.find(executionIsActive)
    setSelectedExecutionKey(executionKey(activeExecution || executionItems[0]))
  }, [executionItems, selectedExecutionKey])

  useEffect(() => {
    const availableBlockIds = new Set((activeTarget?.context_blocks || []).map((item) => item.id))
    setConversationContext((current) => ({
      ...current,
      blockIds: current.blockIds.filter((item) => availableBlockIds.has(item)),
    }))
  }, [activeTarget?.id, activeTarget?.context_blocks])

  const navCounts = useMemo(() => ({
    conversation: activeTarget?.conversation?.length || 0,
    progress: (activeTarget?.decision_journal?.length || 0) + (activeTarget?.sessions?.length || 0),
    approvals: approvalQueue.length,
    jobs: activeExecutionCount,
    shell: activeTarget?.services?.some((service) => ['ssh', 'telnet'].includes(String(service.service || '').toLowerCase()) || [22, 23, 1524, 4444, 6200].includes(Number(service.port || 0))) ? 1 : 0,
    reports: reports?.totals?.findings || 0,
    targets: targets.length,
    loot: observations.length,
    credentials: findCredentialHints(activeTarget).length,
  }), [activeTarget, activeExecutionCount, approvalQueue.length, reports, targets.length, observations.length])

  function renderView() {
    if (!activeTarget && !['targets', 'reports', 'settings', 'team'].includes(activeView)) {
      return (
        <section className="empty-command">
          <span className="hex-icon">AI</span>
          <h2>Ready for first contact</h2>
          <p>Add a target IP to create a case folder, queue baseline enumeration, and populate the operations panels.</p>
        </section>
      )
    }

    if (activeView === 'conversation') {
      return (
        <ConversationView
          activeTarget={activeTarget}
          backendHealth={backendHealth}
          approvalQueue={approvalQueue}
          loading={loading}
          decideAction={decideAction}
          removeAction={removeAction}
          stopExecution={stopExecution}
          selectedExecutionKey={selectedExecutionKey}
          setSelectedExecutionKey={setSelectedExecutionKey}
          sendPrompt={sendPrompt}
          promptDraft={promptDraft}
          setPromptDraft={setPromptDraft}
          promptModel={promptModel}
          setPromptModel={setPromptModel}
          conversationContext={conversationContext}
          setConversationContext={setConversationContext}
          contextForm={contextForm}
          setContextForm={setContextForm}
          addContextBlock={addContextBlock}
          removeContextBlock={removeContextBlock}
          llmPlanner={llmPlanner}
          runPlannerStep={runPlannerStep}
          setPlannerEnabled={setPlannerEnabled}
          commandAllowlist={commandAllowlist}
          targetReport={targetReport}
        />
      )
    }
    if (activeView === 'progress') {
      return (
        <ProgressView
          activeTarget={activeTarget}
          targetReport={targetReport}
          setAutonomyProfile={setAutonomyProfile}
          pauseAutonomy={pauseAutonomy}
          resumeAutonomy={resumeAutonomy}
          loading={loading}
        />
      )
    }
    if (activeView === 'targets') return <TargetsView targets={targets} activeTargetId={activeTargetId} setActiveTargetId={setActiveTargetId} deleteTarget={deleteTarget} loading={loading} />
    if (activeView === 'timeline') return <TimelinePanel entries={[...timeline, ...logs.slice().reverse()]} className="full-view" />
    if (activeView === 'approvals') return <ApprovalsPanel approvalQueue={approvalQueue} loading={loading} decideAction={decideAction} removeAction={removeAction} commandAllowlist={commandAllowlist} />
    if (activeView === 'jobs') return <JobsPanel activeTarget={activeTarget} selectedExecutionKey={selectedExecutionKey} setSelectedExecutionKey={setSelectedExecutionKey} stopExecution={stopExecution} loading={loading} commandAllowlist={commandAllowlist} />
    if (activeView === 'shell') return <ShellView activeTarget={activeTarget} apiBase={apiBase} request={request} />
    if (activeView === 'loot') return <LootView activeTarget={activeTarget} />
    if (activeView === 'credentials') return <CredentialsView activeTarget={activeTarget} />
    if (activeView === 'reports') return <ReportsView reports={reports} activeTarget={activeTarget} targetReport={targetReport} />
    if (activeView === 'team') return <TeamView backendHealth={backendHealth} />
    if (activeView === 'settings') return <SettingsView apiBase={apiBase} setApiBase={setApiBase} uiSettings={uiSettings} setUiSettings={setUiSettings} runtimeSettings={runtimeSettings} diagnostics={diagnostics} modelCatalog={modelCatalog} refreshModelCatalog={refreshModelCatalog} testSettings={testSettings} llmPrompts={llmPrompts} llmPlanner={llmPlanner} updateLlmSettings={updateLlmSettings} setPlannerEnabled={setPlannerEnabled} loading={loading} toolCatalog={toolCatalog} />

    return (
      <DashboardView
        activeTarget={activeTarget}
        backendHealth={backendHealth}
        latestJob={latestJob}
        services={services}
        findings={findings}
        approvalQueue={approvalQueue}
        recommendations={recommendations}
        observations={observations}
        logs={logs}
        timeline={timeline}
        completedActions={completedActions}
        runningJobs={runningJobs}
        loading={loading}
        rerunEnumeration={rerunEnumeration}
        decideAction={decideAction}
        removeAction={removeAction}
        selectedExecutionKey={selectedExecutionKey}
        setSelectedExecutionKey={setSelectedExecutionKey}
        stopExecution={stopExecution}
        commandAllowlist={commandAllowlist}
      />
    )
  }

  return (
    <div className="ops-shell">
      <aside className="ops-sidebar">
        <div className="brand">
          <strong>CYBERLAB</strong>
          <span>OPERATIONS</span>
        </div>
        <nav className="nav-list" aria-label="Primary">
          {NAV_ITEMS.map((item) => (
            <button className={activeView === item.id ? 'active' : ''} key={item.id} type="button" onClick={() => setActiveView(item.id)}>
              <span className="nav-icon">{item.icon}</span>
              {item.label}
              {navCounts[item.id] ? <em>{navCounts[item.id]}</em> : null}
            </button>
          ))}
        </nav>
        <div className="operator-card">
          <div className="avatar">OP</div>
          <div>
            <strong>operator</strong>
            <span>Red Team Operator</span>
            <small>ONLINE</small>
          </div>
        </div>
      </aside>

      <main className="ops-main">
        <header className="topbar">
          <div>
            <h1>{viewTitle}</h1>
            <p>{headerSummary}</p>
          </div>
          <div className="topbar-actions">
            <span className="badge good">
              backend {backendHealth?.status || 'offline'}
            </span>
            <span>{backendHealth?.ollama?.reachable ? 'model online' : 'model offline'}</span>
            <span className="online-dot">ONLINE</span>
          </div>
        </header>

        <section className="control-strip">
          <form className="launch-form" onSubmit={createAndStartTarget}>
            <label>
              Target IP
              <input value={targetIp} onChange={(event) => setTargetIp(event.target.value)} placeholder="10.10.37.25" required />
            </label>
            <label>
              Label
              <input value={targetLabel} onChange={(event) => setTargetLabel(event.target.value)} placeholder="dev-tomcat-01" />
            </label>
            <button className="primary" type="submit" disabled={loading}>{loading ? 'Starting...' : 'Start Enumeration'}</button>
          </form>
          <button type="button" onClick={() => refreshEverything()}>Refresh</button>
          <button type="button" onClick={() => setActiveView('settings')}>Settings</button>
          <button className="danger-button" type="button" disabled={loading || !executionIsActive(selectedExecution)} onClick={() => stopExecution(selectedExecution)}>
            {executionIsActive(selectedExecution) ? 'Stop Operation' : 'No Active Execution'}
          </button>
        </section>

        {error ? <p className="error-banner">{error}</p> : null}
        {renderView()}
      </main>
    </div>
  )
}

createRoot(document.getElementById('root')).render(<App />)
