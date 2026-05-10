import React from 'react'
import { badgeClass, cleanDisplayText } from '../lib/app-utils'
import { EmptyState, Panel } from '../components/primitives'
import { ActionBar, ActionDialog, ActionMenu, ActionNotice, buildWhySections, useActionRuntime } from './dashboard-actions'

export function TargetsView({ targets, activeTargetId, setActiveTargetId, deleteTarget, loading }) {
  const actionRuntime = useActionRuntime()
  const activeTarget = targets.find((target) => target.id === activeTargetId) || targets[0] || null

  return (
    <>
      <div className="view-grid">
        <Panel
          title="Targets"
          meta={targets.length}
          className="wide"
          actions={targets.length ? (
            <ActionMenu
              label="Page Actions"
              actions={[
                {
                  label: 'Ask why',
                  onSelect: () => actionRuntime.showText(
                    'Why the target queue looks this way',
                    buildWhySections([
                      { label: 'Target count', value: `${targets.length} targets are currently tracked in Mission Control.` },
                      { label: 'Active target', value: activeTarget ? `${cleanDisplayText(activeTarget.display_name || activeTarget.ip_address, activeTarget.ip_address)} is selected for detailed operator views.` : 'No target is selected yet.' },
                      { label: 'Operator guidance', value: 'Use the target list to pivot into reports, approvals, and jobs for a specific host without leaving the dashboard workflow.' },
                    ]),
                  ),
                },
                {
                  label: 'Copy active target JSON',
                  disabled: !activeTarget,
                  onSelect: () => actionRuntime.copyJson('Active target JSON', activeTarget),
                },
                {
                  label: 'View raw active target',
                  disabled: !activeTarget,
                  onSelect: () => actionRuntime.showJson('Raw active target', activeTarget),
                },
                {
                  label: 'Jump to reports',
                  onSelect: () => actionRuntime.jump('Reports'),
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
          {activeTarget ? (
            <ActionBar>
              <button type="button" onClick={() => actionRuntime.showText(
                'Why this target is selected',
                buildWhySections([
                  { label: 'Target', value: cleanDisplayText(activeTarget.display_name || activeTarget.ip_address, activeTarget.ip_address) },
                  { label: 'Phase', value: activeTarget.phase || 'unknown' },
                  { label: 'Mission load', value: `${activeTarget.open_ports || 0} open ports and ${activeTarget.pending_actions || 0} pending approvals are currently attached to this target.` },
                ]),
              )}>Ask why</button>
              <button type="button" onClick={() => actionRuntime.copyJson('Active target JSON', activeTarget)}>Copy target JSON</button>
              <button type="button" onClick={() => actionRuntime.showJson('Raw active target', activeTarget)}>View raw target</button>
              <button type="button" onClick={() => actionRuntime.jump('Reports')}>Jump to reports</button>
            </ActionBar>
          ) : null}

          <div className="target-list">
            {targets.map((target) => {
              const label = cleanDisplayText(target.display_name || target.ip_address, target.ip_address)
              return (
                <article className={target.id === activeTargetId ? 'target-option selected' : 'target-option'} key={target.id}>
                  <button className="target-select" type="button" onClick={() => setActiveTargetId(target.id)}>
                    <strong>{label}</strong>
                    <span>{target.ip_address}</span>
                    <em className={badgeClass(target.phase)}>{target.phase}</em>
                    <small>{target.open_ports} ports | {target.pending_actions} approvals</small>
                  </button>
                  <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
                    <ActionMenu
                      compact
                      actions={[
                        {
                          label: 'Ask why',
                          onSelect: () => actionRuntime.showText(
                            `Why ${label} is in scope`,
                            buildWhySections([
                              { label: 'Address', value: target.ip_address || 'No IP recorded.' },
                              { label: 'Phase', value: target.phase || 'unknown' },
                              { label: 'Queue state', value: `${target.open_ports || 0} open ports and ${target.pending_actions || 0} approvals are associated with this target.` },
                            ]),
                          ),
                        },
                        {
                          label: 'Copy target JSON',
                          onSelect: () => actionRuntime.copyJson('Target JSON', target),
                        },
                        {
                          label: 'View raw target',
                          onSelect: () => actionRuntime.showJson('Raw target record', target),
                        },
                        {
                          label: 'Jump to reports',
                          onSelect: () => {
                            setActiveTargetId(target.id)
                            actionRuntime.jump('Reports')
                          },
                        },
                        {
                          label: 'Jump to approvals',
                          onSelect: () => {
                            setActiveTargetId(target.id)
                            actionRuntime.jump('Approvals')
                          },
                        },
                        {
                          label: 'Jump to jobs',
                          onSelect: () => {
                            setActiveTargetId(target.id)
                            actionRuntime.jump('Jobs')
                          },
                        },
                      ]}
                    />
                    <button className="danger-button" type="button" disabled={loading} onClick={() => deleteTarget(target.id, target.display_name || target.ip_address)}>Remove</button>
                  </div>
                </article>
              )
            })}
            {!targets.length ? <EmptyState title="No targets" body="Create a target from the launch controls to begin." /> : null}
          </div>
        </Panel>
      </div>

      <ActionDialog dialog={actionRuntime.dialog} onClose={actionRuntime.closeDialog} />
      <ActionNotice notice={actionRuntime.notice} />
    </>
  )
}
