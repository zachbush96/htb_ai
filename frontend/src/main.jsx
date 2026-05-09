import React, { useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import './styles.css'

function inferDefaultApiBase() {
  if (typeof window === 'undefined') {
    return 'http://127.0.0.1:8000'
  }
  if (window.location.port === '5173') {
    return 'http://127.0.0.1:8000'
  }
  return window.location.origin
}

function badgeClass(value) {
  if (value === 'ready' || value === 'completed' || value === 'enumerated') return 'badge good'
  if (value === 'running' || value === 'queued' || value === 'initial_enumeration') return 'badge warn'
  if (value === 'error' || value === 'failed' || value === 'enumeration_failed') return 'badge danger'
  return 'badge'
}

function formatTime(value) {
  if (!value) return 'n/a'
  try {
    return new Date(value).toLocaleString()
  } catch {
    return value
  }
}

function App() {
  const [apiBase, setApiBase] = useState(() => window.localStorage.getItem('htbmc-api-base') || inferDefaultApiBase())
  const [targets, setTargets] = useState([])
  const [activeTargetId, setActiveTargetId] = useState(null)
  const [activeTarget, setActiveTarget] = useState(null)
  const [targetIp, setTargetIp] = useState('')
  const [targetLabel, setTargetLabel] = useState('')
  const [backendHealth, setBackendHealth] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    window.localStorage.setItem('htbmc-api-base', apiBase)
  }, [apiBase])

  useEffect(() => {
    refreshEverything()
    const interval = window.setInterval(() => {
      refreshEverything(activeTargetId)
    }, 3500)
    return () => window.clearInterval(interval)
  }, [apiBase, activeTargetId])

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

  async function refreshEverything(preferredTargetId = activeTargetId) {
    try {
      const [health, targetList] = await Promise.all([request('/healthz'), request('/api/targets')])
      setBackendHealth(health)
      setTargets(targetList)
      const nextId = preferredTargetId && targetList.some((item) => item.id === preferredTargetId)
        ? preferredTargetId
        : targetList[0]?.id || null
      setActiveTargetId(nextId)
      if (nextId) {
        const detail = await request(`/api/targets/${nextId}`)
        setActiveTarget(detail)
      } else {
        setActiveTarget(null)
      }
      setError('')
    } catch (err) {
      setError(String(err))
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
    } catch (err) {
      setError(String(err))
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
      setError(String(err))
    } finally {
      setLoading(false)
    }
  }

  const latestJob = activeTarget?.jobs?.[activeTarget.jobs.length - 1] || null
  const services = activeTarget?.services || []
  const findings = activeTarget?.findings || []
  const recommendations = activeTarget?.recommendations || []
  const timeline = [...(activeTarget?.timeline || [])].reverse()

  return (
    <div className="shell">
      <header className="masthead">
        <div>
          <p className="eyebrow">HackTheBox Operator Console</p>
          <h1>HTB Mission Control</h1>
          <p className="lede">
            Enter a box IP, start the baseline scan, and keep the early recon state visible in one place.
          </p>
        </div>
        <div className="health-panel">
          <span className={badgeClass(backendHealth ? 'ready' : 'queued')}>
            backend {backendHealth?.status || 'offline'}
          </span>
          <div className="health-meta">
            <span><strong>nmap</strong> {backendHealth?.nmap_bin || 'missing'}</span>
            <span><strong>cases</strong> {backendHealth?.targets ?? 0}</span>
          </div>
        </div>
      </header>

      <section className="control-band">
        <form className="launch-form" onSubmit={createAndStartTarget}>
          <div className="field">
            <label htmlFor="target-ip">Target IP</label>
            <input
              id="target-ip"
              value={targetIp}
              onChange={(event) => setTargetIp(event.target.value)}
              placeholder="10.10.11.42"
              required
            />
          </div>
          <div className="field">
            <label htmlFor="target-label">Label</label>
            <input
              id="target-label"
              value={targetLabel}
              onChange={(event) => setTargetLabel(event.target.value)}
              placeholder="BoardLight"
            />
          </div>
          <button className="primary" type="submit" disabled={loading}>
            {loading ? 'Starting...' : 'Start Enumeration'}
          </button>
        </form>

        <div className="api-form">
          <div className="field">
            <label htmlFor="api-base">API base</label>
            <input
              id="api-base"
              value={apiBase}
              onChange={(event) => setApiBase(event.target.value)}
              placeholder="http://127.0.0.1:8000"
            />
          </div>
          <button type="button" onClick={() => refreshEverything()}>
            Refresh
          </button>
        </div>
      </section>

      {error ? <p className="error-banner">{error}</p> : null}

      <div className="workspace">
        <aside className="sidebar">
          <div className="sidebar-head">
            <h2>Tracked Boxes</h2>
            <span>{targets.length}</span>
          </div>
          <div className="target-list">
            {targets.length === 0 ? (
              <div className="empty-state compact">No cases yet.</div>
            ) : (
              targets.map((target) => (
                <button
                  key={target.id}
                  className={`target-chip ${target.id === activeTargetId ? 'active' : ''}`}
                  onClick={() => setActiveTargetId(target.id)}
                  type="button"
                >
                  <strong>{target.display_name || target.ip_address}</strong>
                  <span>{target.ip_address}</span>
                  <small>{target.latest_summary || target.phase}</small>
                </button>
              ))
            )}
          </div>
        </aside>

        <main className="main-view">
          {!activeTarget ? (
            <section className="hero-empty">
              <h2>Ready for first contact</h2>
              <p>
                Add a target IP to create a case folder, queue the baseline scan, and generate protocol-specific next steps from the result.
              </p>
            </section>
          ) : (
            <>
              <section className="target-header">
                <div>
                  <p className="eyebrow">Active Case</p>
                  <h2>{activeTarget.display_name || activeTarget.ip_address}</h2>
                  <p className="target-subtitle">
                    {activeTarget.ip_address}
                    {activeTarget.hostnames?.length ? ` | ${activeTarget.hostnames.join(', ')}` : ''}
                  </p>
                </div>
                <div className="header-actions">
                  <span className={badgeClass(activeTarget.phase)}>{activeTarget.phase}</span>
                  <button type="button" onClick={rerunEnumeration} disabled={loading}>
                    Re-run Enumeration
                  </button>
                </div>
              </section>

              <section className="metrics-row">
                <article className="metric-panel">
                  <span>Open services</span>
                  <strong>{services.length}</strong>
                </article>
                <article className="metric-panel">
                  <span>Findings</span>
                  <strong>{findings.length}</strong>
                </article>
                <article className="metric-panel">
                  <span>Latest job</span>
                  <strong>{latestJob?.status || 'idle'}</strong>
                </article>
                <article className="metric-panel">
                  <span>Updated</span>
                  <strong>{formatTime(activeTarget.updated_at)}</strong>
                </article>
              </section>

              <section className="summary-band">
                <p>{activeTarget.latest_summary}</p>
              </section>

              <section className="grid-two">
                <article className="panel">
                  <div className="panel-head">
                    <h3>Enumeration Status</h3>
                    <span className={badgeClass(latestJob?.status || 'idle')}>{latestJob?.status || 'idle'}</span>
                  </div>
                  {latestJob ? (
                    <div className="stack">
                      <div className="detail-row"><span>Label</span><strong>{latestJob.label}</strong></div>
                      <div className="detail-row"><span>Queued</span><strong>{formatTime(latestJob.created_at)}</strong></div>
                      <div className="detail-row"><span>Started</span><strong>{formatTime(latestJob.started_at)}</strong></div>
                      <div className="detail-row"><span>Finished</span><strong>{formatTime(latestJob.finished_at)}</strong></div>
                      <div className="detail-block">
                        <span>Command</span>
                        <code>{latestJob.command}</code>
                      </div>
                      {latestJob.error ? (
                        <div className="detail-block">
                          <span>Error</span>
                          <pre>{latestJob.error}</pre>
                        </div>
                      ) : null}
                    </div>
                  ) : (
                    <div className="empty-state">Enumeration has not started yet.</div>
                  )}
                </article>

                <article className="panel">
                  <div className="panel-head">
                    <h3>Discovered Services</h3>
                    <span>{services.length}</span>
                  </div>
                  {services.length ? (
                    <div className="tableish">
                      {services.map((service) => (
                        <div className="tableish-row" key={`${service.protocol}-${service.port}`}>
                          <strong>{service.port}/{service.protocol}</strong>
                          <span>{service.service}</span>
                          <small>{service.detail || 'Banner detail not captured'}</small>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="empty-state">Open ports will appear here once the first scan completes.</div>
                  )}
                </article>
              </section>

              <section className="grid-two">
                <article className="panel">
                  <div className="panel-head">
                    <h3>Next Moves</h3>
                    <span>{recommendations.length}</span>
                  </div>
                  {recommendations.length ? (
                    <div className="stack">
                      {recommendations.map((item) => (
                        <div className="recommendation" key={item.id}>
                          <div className="panel-head">
                            <strong>{item.label}</strong>
                            <span className={badgeClass(item.risk)}>{item.risk}</span>
                          </div>
                          <p>{item.why}</p>
                          <code>{item.command}</code>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="empty-state">Recommendations will populate after service discovery.</div>
                  )}
                </article>

                <article className="panel">
                  <div className="panel-head">
                    <h3>Findings</h3>
                    <span>{findings.length}</span>
                  </div>
                  {findings.length ? (
                    <div className="stack">
                      {findings.map((finding) => (
                        <div className="finding" key={finding.id}>
                          <div className="panel-head">
                            <strong>{finding.title}</strong>
                            <span className={badgeClass(finding.severity)}>{finding.severity}</span>
                          </div>
                          <p>{finding.evidence}</p>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="empty-state">Findings are generated from parsed services.</div>
                  )}
                </article>
              </section>

              <section className="panel">
                <div className="panel-head">
                  <h3>Timeline</h3>
                  <span>{timeline.length}</span>
                </div>
                {timeline.length ? (
                  <div className="timeline">
                    {timeline.map((entry) => (
                      <div className="timeline-row" key={entry.id}>
                        <strong>{entry.type}</strong>
                        <span>{entry.message}</span>
                        <small>{formatTime(entry.timestamp_utc)}</small>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="empty-state">Timeline events will appear here.</div>
                )}
              </section>
            </>
          )}
        </main>
      </div>
    </div>
  )
}

createRoot(document.getElementById('root')).render(<App />)
