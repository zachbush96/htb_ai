import React from 'react'
import { badgeClass, cleanDisplayText, firstHttpUrl, serviceRisk } from '../lib/app-utils'
import { BarChart, EmptyState, Metric, Panel } from '../components/primitives'
import { ActionBar, ActionDialog, ActionMenu, ActionNotice, buildWhySections, useActionRuntime } from './dashboard-actions'

export function ReportsView({ reports, activeTarget, targetReport }) {
  const actionRuntime = useActionRuntime()
  const overview = reports?.totals || {}
  const activeReport = targetReport || reports?.targets?.find((item) => item.id === activeTarget?.id)
  const activeIp = activeReport?.ip_address || activeTarget?.ip_address || null
  const severityRows = Object.entries(activeReport?.severity_counts || {}).map(([label, value]) => ({
    label,
    value,
    tone: ['critical', 'high'].includes(label) ? 'danger' : label === 'medium' ? 'warn' : 'info',
  }))

  return (
    <>
      <div className="view-grid">
        <Panel
          title="Report Overview"
          meta={reports?.generated_at || null}
          className="wide"
          actions={reports ? (
            <ActionMenu
              label="Page Actions"
              actions={[
                {
                  label: 'Ask why',
                  onSelect: () => actionRuntime.showText(
                    'Why the report overview is useful',
                    buildWhySections([
                      { label: 'Coverage', value: `${overview.targets || 0} targets, ${overview.services || 0} services, ${overview.findings || 0} findings, and ${overview.artifacts || 0} artifacts are currently summarized here.` },
                      { label: 'Purpose', value: 'The report overview collapses mission state into a single readout so operators can judge scope before pivoting back into target-specific actions.' },
                    ]),
                  ),
                },
                {
                  label: 'View raw reports',
                  onSelect: () => actionRuntime.showJson('Raw report overview', reports),
                },
                {
                  label: 'Copy raw reports',
                  onSelect: () => actionRuntime.copyJson('Report overview JSON', reports),
                },
                {
                  label: 'Jump to dashboard',
                  onSelect: () => actionRuntime.jump('Dashboard'),
                },
              ]}
            />
          ) : null}
        >
          <ActionBar>
            <button type="button" onClick={() => actionRuntime.showJson('Raw report overview', reports || {})}>View raw input</button>
            <button type="button" onClick={() => actionRuntime.copyJson('Report overview JSON', reports || {})}>Copy report JSON</button>
            <button type="button" onClick={() => actionRuntime.jump('Targets')}>Jump to targets</button>
          </ActionBar>
          <div className="metric-grid">
            <Metric label="Targets" value={overview.targets || 0} />
            <Metric label="Services" value={overview.services || 0} />
            <Metric label="Findings" value={overview.findings || 0} tone="warn" />
            <Metric label="Pending Actions" value={overview.pending_actions || 0} tone="danger" />
            <Metric label="Artifacts" value={overview.artifacts || 0} />
          </div>
        </Panel>

        <Panel
          title="Active Target Report"
          meta={activeReport?.phase || 'no target'}
          className="wide"
          actions={activeReport ? (
            <ActionMenu
              label="Report Actions"
              actions={[
                {
                  label: 'Ask why',
                  onSelect: () => actionRuntime.showText(
                    `Why ${cleanDisplayText(activeReport.display_name || activeReport.ip_address, activeReport.ip_address)} is prioritized`,
                    buildWhySections([
                      { label: 'Summary', value: activeReport.summary || 'No report summary available.' },
                      { label: 'Phase', value: activeReport.phase || 'unknown' },
                      { label: 'Counts', value: `${activeReport.counts.services} services, ${activeReport.counts.findings} findings, ${activeReport.counts.completed_actions} completed actions.` },
                    ]),
                  ),
                },
                {
                  label: 'View raw report',
                  onSelect: () => actionRuntime.showJson('Raw active target report', activeReport),
                },
                {
                  label: 'Copy report JSON',
                  onSelect: () => actionRuntime.copyJson('Active target report JSON', activeReport),
                },
                {
                  label: 'Jump to approvals',
                  onSelect: () => actionRuntime.jump('Approvals'),
                },
                {
                  label: 'Jump to jobs',
                  onSelect: () => actionRuntime.jump('Jobs'),
                },
              ]}
            />
          ) : null}
        >
          {activeReport ? (
            <div className="report-layout">
              <div>
                <h2>{cleanDisplayText(activeReport.display_name || activeReport.ip_address, activeReport.ip_address)}</h2>
                <p>{cleanDisplayText(activeReport.summary, 'No report summary available.')}</p>
                <div className="metric-grid compact-metrics">
                  <Metric label="Services" value={activeReport.counts.services} />
                  <Metric label="Findings" value={activeReport.counts.findings} tone="warn" />
                  <Metric label="Observations" value={activeReport.counts.observations} />
                  <Metric label="Completed" value={activeReport.counts.completed_actions} tone="good" />
                </div>
              </div>
              <BarChart rows={severityRows} />
            </div>
          ) : <EmptyState title="No report selected" body="Select or create a target to populate detailed reports." />}
        </Panel>

        <Panel
          title="Services In Scope"
          className="wide"
          actions={activeReport?.services?.length ? (
            <ActionMenu
              label="Service Actions"
              actions={[
                {
                  label: 'View raw services',
                  onSelect: () => actionRuntime.showJson('Raw report services', activeReport.services),
                },
                {
                  label: 'Copy services JSON',
                  onSelect: () => actionRuntime.copyJson('Report services JSON', activeReport.services),
                },
              ]}
            />
          ) : null}
        >
          {activeReport?.services?.length ? (
            <div className="service-table">
              <div className="table-header"><span>Port</span><span>Proto</span><span>Service</span><span>Detail</span><span>Risk</span><span>Actions</span></div>
              {activeReport.services.map((service) => {
                const endpoint = firstHttpUrl(service, activeIp)
                const serviceName = cleanDisplayText(service.service, 'unknown')
                return (
                  <div className="table-row" key={`${service.protocol}-${service.port}`}>
                    <strong>{service.port}</strong>
                    <span>{service.protocol}</span>
                    <span>{serviceName}</span>
                    <span>{cleanDisplayText(service.detail, 'No version detail captured')}</span>
                    <em className={badgeClass(serviceRisk(service))}>{serviceRisk(service)}</em>
                    <ActionMenu
                      compact
                      actions={[
                        {
                          label: 'Ask why',
                          onSelect: () => actionRuntime.showText(
                            `Why ${serviceName} is highlighted in the report`,
                            buildWhySections([
                              { label: 'Exposure', value: `${service.protocol}/${service.port} is open on ${activeIp || 'the active target'}.` },
                              { label: 'Risk posture', value: serviceRisk(service) },
                              { label: 'Detail', value: service.detail || 'No version detail captured.' },
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
                          onSelect: () => actionRuntime.showJson('Raw report service', { ...service, inferred_endpoint: endpoint }),
                        },
                      ]}
                    />
                  </div>
                )
              })}
            </div>
          ) : <EmptyState title="No services" body="The active report has no services yet." />}
        </Panel>
      </div>

      <ActionDialog dialog={actionRuntime.dialog} onClose={actionRuntime.closeDialog} />
      <ActionNotice notice={actionRuntime.notice} />
    </>
  )
}
