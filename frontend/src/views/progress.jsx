import React from 'react'
import { badgeClass, cleanDisplayText, formatDateTime, formatObjectiveLabel, objectiveTone } from '../lib/app-utils'
import { EmptyState, Metric, Panel } from '../components/primitives'
import { ActionDialog, ActionMenu, ActionNotice, buildWhySections, useActionRuntime } from './dashboard-actions'

function GraphNodeList({ nodes }) {
  if (!nodes.length) return <EmptyState title="No graph nodes" body="Enumerate a target or complete actions to populate the attack graph." />
  return (
    <div className="finding-list">
      {nodes.map((node) => (
        <article key={node.id}>
          <span className={`alert-dot ${objectiveTone(node.status)}`} />
          <div>
            <strong>{cleanDisplayText(node.label, node.kind)}</strong>
            <p>{cleanDisplayText(node.kind, 'node')}</p>
          </div>
          <em className={badgeClass(node.status)}>{node.status}</em>
        </article>
      ))}
    </div>
  )
}

export function ProgressView({
  activeTarget,
  targetReport,
  setAutonomyProfile,
  pauseAutonomy,
  resumeAutonomy,
  loading,
}) {
  const actionRuntime = useActionRuntime()
  const report = targetReport?.id === activeTarget?.id ? targetReport : activeTarget
  const autonomy = report?.autonomy || {}
  const objectives = report?.objectives || { current_phase: 'recon', states: {} }
  const graph = report?.attack_graph || { nodes: [], edges: [] }
  const bestPath = report?.best_path || null
  const journal = report?.decision_journal || activeTarget?.decision_journal || []
  const credentials = report?.credentials || activeTarget?.credentials || []
  const sessions = report?.sessions || activeTarget?.sessions || []

  return (
    <>
      <div className="view-grid">
        <Panel
          title="Attack Progress"
          meta={formatObjectiveLabel(objectives.current_phase)}
          className="wide"
          actions={(
            <ActionMenu
              label="Progress Actions"
              actions={[
                {
                  label: 'View raw progress',
                  onSelect: () => actionRuntime.showJson('Progress state', { report, autonomy, objectives, graph, bestPath, journal }),
                },
                {
                  label: autonomy.paused ? 'Resume autonomy' : 'Pause autonomy',
                  onSelect: () => (autonomy.paused ? resumeAutonomy() : pauseAutonomy()),
                  disabled: loading,
                },
              ]}
            />
          )}
        >
          <div className="metric-grid">
            <Metric label="Objective" value={formatObjectiveLabel(objectives.current_phase)} tone={objectiveTone(objectives.current_phase)} />
            <Metric label="Credentials" value={credentials.length} tone={credentials.length ? 'warn' : 'info'} />
            <Metric label="Sessions" value={sessions.length} tone={sessions.length ? 'good' : 'info'} />
            <Metric label="Graph Nodes" value={graph.nodes?.length || 0} />
            <Metric label="Graph Edges" value={graph.edges?.length || 0} />
          </div>
          <div className="button-row">
            <button type="button" disabled={loading} onClick={() => setAutonomyProfile('recon_only')}>Recon Only</button>
            <button type="button" disabled={loading} onClick={() => setAutonomyProfile('through_foothold')}>Through Foothold</button>
            <button className="primary" type="button" disabled={loading} onClick={() => setAutonomyProfile('through_privesc')}>Through Privesc</button>
            <button type="button" disabled={loading} onClick={() => (autonomy.paused ? resumeAutonomy() : pauseAutonomy())}>
              {autonomy.paused ? 'Resume' : 'Pause'}
            </button>
          </div>
          {autonomy.pause_reason ? <p className="error-banner">{autonomy.pause_reason}</p> : null}
        </Panel>

        <Panel
          title="Best Path"
          meta={bestPath?.next_objective || 'pending'}
          className="wide"
          actions={bestPath ? (
            <ActionMenu
              label="Path Actions"
              actions={[
                {
                  label: 'Ask why',
                  onSelect: () => actionRuntime.showText(
                    'Why this path is highest priority',
                    buildWhySections([
                      { label: 'Path', value: bestPath.label || 'No label' },
                      { label: 'Why', value: bestPath.why || 'No rationale stored.' },
                      { label: 'Next objective', value: bestPath.next_objective || 'unknown' },
                    ]),
                  ),
                },
                {
                  label: 'Copy best path JSON',
                  onSelect: () => actionRuntime.copyJson('Best path JSON', bestPath),
                },
              ]}
            />
          ) : null}
        >
          {bestPath ? (
            <div className="report-layout">
              <div>
                <h2>{cleanDisplayText(bestPath.label, 'No path label')}</h2>
                <p>{cleanDisplayText(bestPath.why, 'No path rationale stored yet.')}</p>
              </div>
              <div className="context-preview">
                <article>
                  <strong>Confidence</strong>
                  <span>{cleanDisplayText(bestPath.confidence, 'candidate')}</span>
                </article>
                <article>
                  <strong>Next Objective</strong>
                  <span>{cleanDisplayText(bestPath.next_objective, 'pending')}</span>
                </article>
              </div>
            </div>
          ) : <EmptyState title="No best path yet" body="Mission Control will promote the highest-confidence route as evidence accumulates." />}
        </Panel>

        <Panel title="Attack Graph Nodes" meta={graph.nodes?.length || 0} className="wide">
          <GraphNodeList nodes={graph.nodes || []} />
        </Panel>

        <Panel title="Decision Journal" meta={journal.length} className="wide">
          <div className="execution-list">
            {journal.slice().reverse().map((entry) => (
              <article key={entry.id}>
                <strong>{cleanDisplayText(entry.title, 'Journal entry')}</strong>
                <span>{formatDateTime(entry.timestamp_utc)}</span>
                <p>{cleanDisplayText(entry.summary, 'No summary stored.')}</p>
                <ActionMenu
                  compact
                  actions={[
                    {
                      label: 'Ask why',
                      onSelect: () => actionRuntime.showText(
                        cleanDisplayText(entry.title, 'Decision journal'),
                        buildWhySections([
                          { label: 'Summary', value: entry.summary || 'No summary stored.' },
                          { label: 'What changed', value: entry.what_changed || 'Not recorded.' },
                          { label: 'Stop condition', value: entry.what_would_stop || 'Not recorded.' },
                        ]),
                      ),
                    },
                    {
                      label: 'View raw journal entry',
                      onSelect: () => actionRuntime.showJson('Journal entry', entry),
                    },
                  ]}
                />
              </article>
            ))}
            {!journal.length ? <EmptyState title="No journal entries" body="Planner turns and structured pivots will be recorded here." /> : null}
          </div>
        </Panel>
      </div>

      <ActionDialog dialog={actionRuntime.dialog} onClose={actionRuntime.closeDialog} />
      <ActionNotice notice={actionRuntime.notice} />
    </>
  )
}
