import React from 'react'
import { badgeClass, cleanDisplayText, formatDateTime, riskClass } from '../lib/app-utils'
import { EmptyState, Panel } from '../components/primitives'
import { buildWhyItems, extractArtifactPath, extractDetectedVersion, extractFirstUrl, openInBrowser, OpsActionMenu, OpsCopyNote, OpsMetaGrid, OpsRawBlock, OpsWhyList, safeSerialize } from './ops-actions'

function ObservationActions({ item }) {
  const browserUrl = extractFirstUrl(item.summary, item.title)
  const detectedVersion = extractDetectedVersion(item.title, item.summary)

  return (
    <OpsActionMenu
      itemLabel="observation"
      actions={[
        {
          id: 'ask-why',
          type: 'panel',
          label: 'Ask why',
          description: 'Review why this observation was captured.',
          renderPanel: () => (
            <>
              <OpsWhyList items={buildWhyItems(item, [
                item.confidence ? `Evidence confidence is ${item.confidence}.` : '',
                item.port ? `Observation is tied to port ${item.port}.` : '',
              ])} />
              <OpsMetaGrid items={[
                { label: 'Severity', value: item.severity || 'info' },
                { label: 'Confidence', value: item.confidence || 'n/a' },
                { label: 'Port', value: item.port ?? 'n/a' },
              ]} />
            </>
          ),
        },
        {
          id: 'raw-io',
          type: 'panel',
          label: 'View raw input/output',
          description: 'Inspect the raw observation payload.',
          renderPanel: () => <OpsRawBlock title="Observation JSON" value={safeSerialize(item)} />,
        },
        {
          id: 'copy-summary',
          type: 'copy',
          label: 'Copy summary',
          value: item.summary || '',
          disabled: !item.summary,
          description: 'Observation summary copied to the clipboard.',
        },
        {
          id: 'copy-json',
          type: 'copy',
          label: 'Copy observation JSON',
          value: safeSerialize(item),
          description: 'Observation JSON copied to the clipboard.',
        },
        {
          id: 'copy-version',
          type: 'copy',
          label: 'Copy device version',
          hidden: !detectedVersion,
          value: detectedVersion || '',
          description: 'Detected version string copied to the clipboard.',
        },
        {
          id: 'open-browser',
          type: 'open',
          label: 'Open in browser',
          hidden: !browserUrl,
          description: 'Opening the first detected URL from this observation.',
          onClick: () => openInBrowser(browserUrl),
        },
      ]}
    />
  )
}

function ArtifactActions({ item }) {
  const browserUrl = extractFirstUrl(item.command, item.result_excerpt, item.parse_summary)
  const artifactPath = extractArtifactPath(item)
  const detectedVersion = extractDetectedVersion(item.result_excerpt, item.parse_summary, item.summary)

  return (
    <OpsActionMenu
      itemLabel="artifact"
      actions={[
        {
          id: 'ask-why',
          type: 'panel',
          label: 'Ask why',
          description: 'Review how this artifact was produced.',
          renderPanel: () => (
            <>
              <OpsWhyList items={buildWhyItems(item, [
                artifactPath ? 'A persisted artifact path is available for operator follow-up.' : '',
                item.finished_at ? `Execution finished at ${formatDateTime(item.finished_at)}.` : '',
              ])} />
              <OpsMetaGrid items={[
                { label: 'Status', value: item.status || 'unknown' },
                { label: 'Artifact path', value: artifactPath || 'n/a' },
                { label: 'Finished', value: formatDateTime(item.finished_at || item.updated_at || item.created_at) },
              ]} />
            </>
          ),
        },
        {
          id: 'raw-io',
          type: 'panel',
          label: 'View raw input/output',
          description: 'Inspect the raw command, result excerpt, and artifact JSON.',
          renderPanel: () => (
            <>
              <OpsRawBlock title="Command Input" value={item.command} empty="No command recorded." />
              <OpsRawBlock title="Result Output" value={item.result_excerpt || item.parse_summary || item.summary || 'No parsed output recorded.'} />
              <OpsRawBlock title="Artifact JSON" value={safeSerialize(item)} />
            </>
          ),
        },
        {
          id: 'copy-command',
          type: 'copy',
          label: 'Copy command',
          value: item.command || '',
          disabled: !item.command,
          description: 'Artifact command copied to the clipboard.',
        },
        {
          id: 'copy-artifact-path',
          type: 'copy',
          label: 'Copy artifact path',
          hidden: !artifactPath,
          value: artifactPath || '',
          description: 'Artifact path copied to the clipboard.',
        },
        {
          id: 'artifact-details',
          type: 'panel',
          label: 'Open artifact details',
          hidden: !artifactPath,
          description: 'Review artifact path and completion metadata.',
          renderPanel: () => (
            <>
              <OpsMetaGrid items={[
                { label: 'Artifact path', value: artifactPath },
                { label: 'Status', value: item.status || 'unknown' },
                { label: 'Created', value: formatDateTime(item.created_at) },
                { label: 'Finished', value: formatDateTime(item.finished_at || item.updated_at) },
              ]} />
              <OpsRawBlock title="Artifact Path" value={artifactPath} />
            </>
          ),
        },
        {
          id: 'open-browser',
          type: 'open',
          label: 'Open in browser',
          hidden: !browserUrl,
          description: 'Opening the first detected URL tied to this artifact.',
          onClick: () => openInBrowser(browserUrl),
        },
        {
          id: 'copy-version',
          type: 'copy',
          label: 'Copy detected version',
          hidden: !detectedVersion,
          value: detectedVersion || '',
          description: 'Detected version string copied to the clipboard.',
        },
      ]}
    />
  )
}

export function LootView({ activeTarget }) {
  const observations = activeTarget?.observations || []
  const completed = (activeTarget?.agent_actions || []).filter((item) => item.status === 'completed' && (item.result_excerpt || item.output_path))
  const credentials = activeTarget?.credentials || []
  const sessions = activeTarget?.sessions || []

  return (
    <div className="view-grid">
      <Panel title="Collected Observations" meta={observations.length} className="wide">
        <div className="finding-list">
          {observations.slice().reverse().map((item, index) => (
            <article key={item.id || `${item.title}-${index}`}>
              <span className={`alert-dot ${riskClass(item.severity)}`} />
              <div>
                <strong>{cleanDisplayText(item.title, 'Observation')}</strong>
                <p>{cleanDisplayText(item.summary, 'No observation summary available.')}</p>
                <ObservationActions item={item} />
              </div>
              <em className={badgeClass(item.severity)}>{item.severity}</em>
            </article>
          ))}
          {!observations.length ? <EmptyState title="No loot yet" body="Approved actions will add parsed observations here." /> : null}
        </div>
        {observations.length ? <OpsCopyNote>Observation actions include rationale review, raw payload access, summary copy, and a version extractor when banner text exposes one.</OpsCopyNote> : null}
      </Panel>
      <Panel title="Harvested Credentials" meta={credentials.length} className="wide">
        <div className="execution-list">
          {credentials.map((item) => (
            <article key={item.id}>
              <strong>{cleanDisplayText(item.label, 'credential')}</strong>
              <span>{cleanDisplayText(item.status, 'candidate')}</span>
              <p>{cleanDisplayText(item.summary, 'No credential summary stored.')}</p>
            </article>
          ))}
          {!credentials.length ? <EmptyState title="No credentials" body="Structured credential candidates will appear here when actions expose them." /> : null}
        </div>
      </Panel>
      <Panel title="Sessions" meta={sessions.length} className="wide">
        <div className="execution-list">
          {sessions.map((item) => (
            <article key={item.id}>
              <strong>{cleanDisplayText(item.label, 'session')}</strong>
              <span>{cleanDisplayText(item.status, 'active')}</span>
              <p>{cleanDisplayText(item.summary, 'No session summary stored.')}</p>
            </article>
          ))}
          {!sessions.length ? <EmptyState title="No sessions" body="Footholds and shell indicators will be preserved here." /> : null}
        </div>
      </Panel>
      <Panel title="Action Artifacts" meta={completed.length} className="wide">
        <div className="execution-list">
          {completed.map((item) => (
            <article key={item.id}>
              <strong>{cleanDisplayText(item.label, 'Artifact')}</strong>
              <span>{cleanDisplayText(item.output_path, 'stored in target state')}</span>
              <p>{cleanDisplayText(item.result_excerpt || item.parse_summary, 'Artifact recorded.')}</p>
              <ArtifactActions item={item} />
            </article>
          ))}
          {!completed.length ? <EmptyState title="No artifacts" body="Completed actions with output will appear here." /> : null}
        </div>
        {completed.length ? <OpsCopyNote>Completed artifacts now expose artifact-path copy, raw input/output inspection, browser handoff, and structured detail panels without leaving the loot view.</OpsCopyNote> : null}
      </Panel>
    </div>
  )
}
