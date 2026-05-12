import React from 'react'
import { badgeClass, buildExecutionItems, cleanDisplayText, executionIsActive, executionKey, firstHttpUrl, serviceRisk } from '../lib/app-utils'
import { BarChart, Donut, EmptyState, Panel } from '../components/primitives'
import { ActionBar, ActionDialog, ActionMenu, ActionNotice, buildWhySections, useActionRuntime } from './dashboard-actions'
import { ApprovalsPanel } from './approvals'
import { JobsPanel } from './jobs'
import { TimelinePanel } from './timeline'

function FindingsPanel({ findings, observations, actionRuntime }) {
  const items = [...findings, ...observations].slice(0, 6)

  return (
    <Panel title="Related Findings" meta={findings.length}>
      <div className="finding-list">
        {items.map((finding, index) => (
          <article key={finding.id || `${finding.title}-${index}`}>
            <span className={`alert-dot ${String(finding.severity || 'info')}`} />
            <div>
              <strong>{cleanDisplayText(finding.title, 'Finding')}</strong>
              <p>{cleanDisplayText(finding.evidence || finding.summary, 'No evidence summary yet.')}</p>
            </div>
            <em className={badgeClass(finding.severity)}>{finding.severity}</em>
            <ActionMenu
              compact
              actions={[
                {
                  label: 'Ask why',
                  onSelect: () => actionRuntime.showText(
                    `Why ${cleanDisplayText(finding.title, 'this finding')} matters`,
                    buildWhySections([
                      { label: 'Severity', value: finding.severity || 'unknown' },
                      { label: 'Evidence', value: finding.evidence || finding.summary || 'No evidence summary recorded.' },
                    ]),
                  ),
                },
                {
                  label: 'Copy evidence',
                  onSelect: () => actionRuntime.copyText('Finding evidence', finding.evidence || finding.summary || finding.title || 'No evidence recorded'),
                },
                {
                  label: 'View raw finding',
                  onSelect: () => actionRuntime.showJson('Raw finding record', finding),
                },
              ]}
            />
          </article>
        ))}
        {!findings.length && !observations.length ? <EmptyState title="No findings" body="Parsed findings will appear here." /> : null}
      </div>
    </Panel>
  )
}

function ExecutionPanel({ completedActions, actionRuntime }) {
  return (
    <Panel title="Execution History" meta={completedActions.length}>
      <div className="execution-list">
        {completedActions.slice(-6).reverse().map((item) => (
          <article key={item.id}>
            <strong>{cleanDisplayText(item.label, 'Completed action')}</strong>
            <span className={badgeClass(item.status)}>{item.status}</span>
            <p>{cleanDisplayText(item.parse_summary || item.summary, 'No parse summary yet.')}</p>
            <ActionMenu
              compact
              actions={[
                {
                  label: 'Ask why',
                  onSelect: () => actionRuntime.showText(
                    `Why ${cleanDisplayText(item.label, 'this action')} completed`,
                    buildWhySections([
                      { label: 'Status', value: item.status || 'unknown' },
                      { label: 'Reason', value: item.reason || item.summary || item.parse_summary || 'No explanation recorded.' },
                    ]),
                  ),
                },
                {
                  label: 'View raw input',
                  onSelect: () => actionRuntime.showJson('Raw action input', item),
                },
                {
                  label: 'View raw output',
                  onSelect: () => actionRuntime.showText('Raw action output', item.live_output_tail || item.result_excerpt || item.error || 'No output captured yet.'),
                },
                {
                  label: 'Copy artifact path',
                  disabled: !item.output_path,
                  onSelect: () => actionRuntime.copyText('Artifact path', item.output_path),
                },
              ]}
            />
          </article>
        ))}
        {!completedActions.length ? <EmptyState title="No executions" body="Approved command executions will appear here." /> : null}
      </div>
    </Panel>
  )
}

export function DashboardView({ activeTarget, backendHealth, latestJob, services, findings, approvalQueue, recommendations, observations, logs, timeline, completedActions, runningJobs, loading, rerunEnumeration, decideAction, removeAction, selectedExecutionKey, setSelectedExecutionKey, stopExecution, commandAllowlist }) {
  const actionRuntime = useActionRuntime()
  const riskScore = Math.min(99, 35 + findings.length * 12 + approvalQueue.length * 9 + services.length * 3)
  const targetName = activeTarget?.display_name || activeTarget?.ip_address || 'No active target'
  const hostName = activeTarget?.hostnames?.[0] || activeTarget?.label || 'pending hostname'
  const displayTargetName = cleanDisplayText(targetName, 'No active target')
  const displayHostName = cleanDisplayText(hostName, 'pending hostname')
  const missionTotal = Math.max(1, services.length + findings.length + approvalQueue.length + runningJobs.length)
  const chartRows = [
    { label: 'Services', value: services.length, tone: 'info' },
    { label: 'Findings', value: findings.length, tone: findings.length ? 'warn' : 'good' },
    { label: 'Approvals', value: approvalQueue.length, tone: approvalQueue.length ? 'danger' : 'good' },
    { label: 'Running jobs', value: runningJobs.length, tone: runningJobs.length ? 'warn' : 'info' },
  ]
  const executionItems = buildExecutionItems(activeTarget)
  const selectedExecution = executionItems.find((item) => executionKey(item) === selectedExecutionKey) || executionItems[0] || null

  const dashboardWhy = buildWhySections([
    { label: 'Target', value: `${displayTargetName} (${activeTarget?.ip_address || 'no IP'})` },
    { label: 'Mission state', value: `${services.length} services, ${findings.length} findings, ${approvalQueue.length} approvals, ${runningJobs.length} running jobs.` },
    { label: 'Operator guidance', value: riskScore > 70 ? 'Risk is elevated, so the approval queue should be reviewed before exploit steps.' : 'Enumeration is stable enough to keep building evidence and validating follow-up actions.' },
    { label: 'Latest execution', value: selectedExecution?.title || latestJob?.label || latestJob?.command || 'No execution selected yet.' },
  ])

  return (
    <>
      <div className="dashboard-grid">
        <Panel title="Operator Actions" meta={displayTargetName} className="wide">
          <ActionBar>
            <button type="button" onClick={() => actionRuntime.showText('Why this dashboard matters', dashboardWhy)}>Ask why</button>
            <button type="button" onClick={() => actionRuntime.showJson('Raw target JSON', activeTarget)}>View raw target</button>
            <button type="button" onClick={() => actionRuntime.copyJson('Target JSON', activeTarget)}>Copy target JSON</button>
            <button type="button" onClick={() => actionRuntime.showJson('Raw execution input', selectedExecution || approvalQueue[0] || latestJob || activeTarget)}>View raw input</button>
            <button type="button" onClick={() => actionRuntime.showText('Raw execution output', selectedExecution?.live_output_tail || selectedExecution?.result_excerpt || selectedExecution?.error || latestJob?.result_excerpt || 'No output captured yet.')}>View raw output</button>
            <button type="button" onClick={() => actionRuntime.jump('Approvals')}>Jump to approvals</button>
            <button type="button" onClick={() => actionRuntime.jump('Jobs')}>Jump to jobs</button>
          </ActionBar>
        </Panel>

        <section className="target-card panel">
          <div className="target-identity">
            <span className="hex-icon">TG</span>
            <div>
              <span className="eyebrow">Active Target</span>
              <h2>{activeTarget.ip_address}</h2>
              <p>{displayHostName} <span>{displayTargetName}</span></p>
            </div>
          </div>
          <div style={{ display: 'flex', gap: '0.6rem', alignItems: 'center' }}>
            <span className={badgeClass(activeTarget.phase)}>{activeTarget.phase}</span>
            <ActionMenu
              compact
              actions={[
                {
                  label: 'Ask why',
                  onSelect: () => actionRuntime.showText('Why this target is active', dashboardWhy),
                },
                {
                  label: 'Copy target JSON',
                  onSelect: () => actionRuntime.copyJson('Target JSON', activeTarget),
                },
                {
                  label: 'View raw target',
                  onSelect: () => actionRuntime.showJson('Raw target JSON', activeTarget),
                },
                {
                  label: 'Jump to reports',
                  onSelect: () => actionRuntime.jump('Reports'),
                },
              ]}
            />
          </div>
        </section>

        <section className="risk-card panel">
          <div>
            <span className="eyebrow">Risk Score</span>
            <strong>{riskScore}<small>/100</small></strong>
          </div>
          <div className="risk-copy">
            <b>{riskScore > 70 ? 'High Risk' : 'Monitored'}</b>
            <span>{riskScore > 70 ? 'Review approval queue before exploit steps.' : 'Continue evidence-backed enumeration.'}</span>
            <div className="risk-bars" aria-label={`Risk score ${riskScore} out of 100`}>
              {Array.from({ length: 6 }).map((_, index) => <i className={index < Math.ceil(riskScore / 17) ? 'on' : ''} key={index} />)}
            </div>
          </div>
        </section>

        <section className="mission-card panel">
          <div className="panel-head compact">
            <h3>Mission Status</h3>
            <span>{latestJob?.finished_at || latestJob?.started_at || '--:--:--'}</span>
          </div>
          <div className="mission-charts">
            <Donut label="Services" value={services.length} total={missionTotal} tone="info" />
            <Donut label="Findings" value={findings.length} total={missionTotal} tone={findings.length ? 'warn' : 'good'} />
            <Donut label="Approvals" value={approvalQueue.length} total={missionTotal} tone={approvalQueue.length ? 'danger' : 'good'} />
          </div>
          <BarChart rows={chartRows} />
        </section>

        <Panel
          title="Key Ports Discovered"
          className="wide"
          actions={services.length ? (
            <ActionMenu
              label="Panel Actions"
              actions={[
                {
                  label: 'Ask why',
                  onSelect: () => actionRuntime.showText(
                    'Why these services are surfaced',
                    buildWhySections([
                      { label: 'Selection logic', value: 'The dashboard promotes current open ports from the active target so operators can validate exposure and select next actions quickly.' },
                      { label: 'Count', value: `${services.length} service records are currently in scope.` },
                    ]),
                  ),
                },
                {
                  label: 'View raw services',
                  onSelect: () => actionRuntime.showJson('Raw services payload', services),
                },
              ]}
            />
          ) : null}
        >
          {services.length ? (
            <div className="service-table">
              <div className="table-header"><span>Port</span><span>Proto</span><span>Service</span><span>Version / Info</span><span>Risk</span><span>Actions</span></div>
              {services.map((service) => {
                const endpoint = firstHttpUrl(service, activeTarget?.ip_address)
                const serviceName = cleanDisplayText(service.service, 'unknown')
                return (
                  <div className="table-row" key={`${service.protocol}-${service.port}`}>
                    <strong>{service.port}</strong>
                    <span>{service.protocol}</span>
                    <span>{serviceName}</span>
                    <span>{cleanDisplayText(service.detail, 'Banner detail not captured')}</span>
                    <em className={badgeClass(serviceRisk(service))}>{serviceRisk(service)}</em>
                    <ActionMenu
                      compact
                      actions={[
                        {
                          label: 'Ask why',
                          onSelect: () => actionRuntime.showText(
                            `Why ${serviceName} is interesting`,
                            buildWhySections([
                              { label: 'Exposure', value: `${service.protocol}/${service.port} is open on ${activeTarget?.ip_address}.` },
                              { label: 'Banner', value: service.detail || 'No banner detail captured.' },
                              { label: 'Risk', value: serviceRisk(service) },
                              { label: 'Operator note', value: endpoint ? `A browser endpoint is available at ${endpoint}.` : 'No browser-friendly endpoint was inferred from this service.' },
                            ]),
                          ),
                        },
                        {
                          label: 'Open in browser',
                          disabled: !endpoint,
                          onSelect: () => actionRuntime.openBrowser(endpoint),
                        },
                        {
                          label: 'Copy endpoint',
                          disabled: !endpoint,
                          onSelect: () => actionRuntime.copyText('Service endpoint', endpoint),
                        },
                        {
                          label: 'Copy service version',
                          onSelect: () => actionRuntime.copyText('Service version', service.detail || service.service || `port ${service.port}`),
                        },
                        {
                          label: 'View raw service',
                          onSelect: () => actionRuntime.showJson('Raw service record', { ...service, inferred_endpoint: endpoint }),
                        },
                      ]}
                    />
                  </div>
                )
              })}
            </div>
          ) : <EmptyState title="No ports yet" body="Open ports will appear once the first scan completes." />}
        </Panel>

        <Panel
          title="Next Steps"
          meta={`model: ${backendHealth?.ollama?.reachable ? 'available' : 'heuristic'}`}
          actions={recommendations.length ? (
            <ActionMenu
              label="Panel Actions"
              actions={[
                {
                  label: 'View raw recommendations',
                  onSelect: () => actionRuntime.showJson('Raw recommendations payload', recommendations),
                },
                {
                  label: 'Jump to approvals',
                  onSelect: () => actionRuntime.jump('Approvals'),
                },
              ]}
            />
          ) : null}
        >
          {recommendations.length ? (
            <div className="rank-list">
              {recommendations.slice(0, 5).map((item, index) => (
                <article key={item.id}>
                  <b>{index + 1}</b>
                  <div><strong>{cleanDisplayText(item.label, 'Recommendation')}</strong><span>{cleanDisplayText(item.why, 'No reason provided.')}</span></div>
                  <em className={badgeClass(item.risk)}>{item.risk || item.status || 'review'}</em>
                  <ActionMenu
                    compact
                    actions={[
                      {
                        label: 'Ask why',
                        onSelect: () => actionRuntime.showText(
                          `Why recommend ${cleanDisplayText(item.label, 'this step')}`,
                          buildWhySections([
                            { label: 'Recommendation', value: item.label || 'No label recorded.' },
                            { label: 'Reason', value: item.why || item.summary || 'No recommendation reason recorded.' },
                            { label: 'Risk', value: item.risk || item.status || 'review' },
                          ]),
                        ),
                      },
                      {
                        label: 'View raw recommendation',
                        onSelect: () => actionRuntime.showJson('Raw recommendation', item),
                      },
                      {
                        label: 'Copy recommendation',
                        onSelect: () => actionRuntime.copyText('Recommendation text', `${item.label || 'Recommendation'}\n${item.why || item.summary || ''}`),
                      },
                    ]}
                  />
                </article>
              ))}
            </div>
          ) : <EmptyState title="No recommendations" body="Recommendations will populate after service discovery." />}
        </Panel>

        <ApprovalsPanel approvalQueue={approvalQueue} loading={loading} decideAction={decideAction} removeAction={removeAction} commandAllowlist={commandAllowlist} />
        <JobsPanel activeTarget={activeTarget} selectedExecutionKey={selectedExecutionKey} setSelectedExecutionKey={setSelectedExecutionKey} stopExecution={stopExecution} loading={loading} condensed commandAllowlist={commandAllowlist} />
        <FindingsPanel findings={findings} observations={observations} actionRuntime={actionRuntime} />

        <Panel
          title="Command Preview"
          className="wide"
          actions={(
            <ActionMenu
              label="Command Actions"
              actions={[
                {
                  label: 'Ask why',
                  onSelect: () => actionRuntime.showText(
                    'Why this command is in focus',
                    buildWhySections([
                      { label: 'Current source', value: approvalQueue[0]?.label || selectedExecution?.title || latestJob?.label || 'No execution selected.' },
                      { label: 'Selection rule', value: 'The preview prioritizes the next pending approval, then the selected execution, then the latest job command.' },
                    ]),
                  ),
                },
                {
                  label: 'View raw input',
                  onSelect: () => actionRuntime.showJson('Raw command source', selectedExecution || approvalQueue[0] || latestJob || activeTarget),
                },
                {
                  label: 'View raw output',
                  onSelect: () => actionRuntime.showText('Raw output tail', selectedExecution?.live_output_tail || selectedExecution?.result_excerpt || selectedExecution?.error || latestJob?.result_excerpt || 'No output captured yet.'),
                },
                {
                  label: 'Jump to jobs',
                  onSelect: () => actionRuntime.jump('Jobs'),
                },
              ]}
            />
          )}
        >
          <code className="command-line">{approvalQueue[0]?.command || latestJob?.command || 'No command selected. Start or re-run enumeration to populate the queue.'}</code>
          <div style={{ display: 'flex', gap: '0.6rem', flexWrap: 'wrap' }}>
            <button type="button" onClick={rerunEnumeration} disabled={loading}>Re-run Enumeration</button>
            <button type="button" onClick={() => actionRuntime.copyText('Command', approvalQueue[0]?.command || latestJob?.command || 'No command recorded.')}>Copy command</button>
          </div>
        </Panel>

        <TimelinePanel entries={[...timeline, ...logs.slice().reverse()].slice(0, 10)} className="wide" />
        <ExecutionPanel completedActions={completedActions} actionRuntime={actionRuntime} />
      </div>

      <ActionDialog dialog={actionRuntime.dialog} onClose={actionRuntime.closeDialog} />
      <ActionNotice notice={actionRuntime.notice} />
    </>
  )
}
