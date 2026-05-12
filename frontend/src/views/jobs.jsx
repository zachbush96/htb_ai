import React from 'react'
import { badgeClass, buildExecutionItems, cleanDisplayText, commandIsAllowlisted, commandLooksLikeInstall, commandNameFromItem, executionExitLabel, executionIsActive, executionKey, executionStatusCopy, formatBytes, formatDateTime, formatRelativeTime, formatTime } from '../lib/app-utils'
import { EmptyState, Panel } from '../components/primitives'
import { buildWhyItems, extractArtifactPath, extractDetectedVersion, extractFirstUrl, openInBrowser, OpsActionMenu, OpsCopyNote, OpsMetaGrid, OpsRawBlock, OpsWhyList, safeSerialize } from './ops-actions'

function ExecutionActions({ item, condensed = false, commandAllowlist }) {
  const browserUrl = extractFirstUrl(item.command, item.result_excerpt, item.live_output_tail, item.error)
  const artifactPath = extractArtifactPath(item)
  const detectedVersion = extractDetectedVersion(item.result_excerpt, item.live_output_tail, item.parse_summary, item.summary)
  const rawOutput = item.live_output_tail || item.result_excerpt || item.error || 'No output captured yet.'
  const allowlisted = commandIsAllowlisted(item, commandAllowlist)
  const installGated = commandLooksLikeInstall(item)

  return (
    <OpsActionMenu
      itemLabel="execution"
      actions={[
        {
          id: 'ask-why',
          type: 'panel',
          label: 'Ask why',
          description: 'Review execution rationale and current state.',
          renderPanel: () => (
            <>
              <OpsWhyList items={buildWhyItems(item, [
                executionStatusCopy(item),
                allowlisted ? `${commandNameFromItem(item)} is on the operator command allowlist and is shown as auto-allowed/default.` : '',
                installGated ? 'Software installation remains approval-gated in the queue before execution.' : '',
                item.output_path ? 'An artifact path has been recorded for this execution.' : '',
                condensed ? 'This execution is shown inside the condensed live monitor.' : '',
              ])} />
              <OpsMetaGrid items={[
                { label: 'Execution kind', value: item.category_label || item.execution_kind || 'unknown' },
                { label: 'Status', value: item.status || 'unknown' },
                { label: 'PID', value: item.pid || 'n/a' },
                { label: 'Exit', value: executionExitLabel(item) },
                { label: 'Allowlist', value: allowlisted ? 'auto-allowed/default' : 'manual review' },
              ]} />
            </>
          ),
        },
        {
          id: 'raw-io',
          type: 'panel',
          label: 'View raw input/output',
          description: 'Inspect the raw command, output tail, and execution JSON.',
          renderPanel: () => (
            <>
              <OpsRawBlock title="Raw Command Input" value={item.command} empty="No command recorded." />
              <OpsRawBlock title="Raw Output Tail" value={rawOutput} />
              <OpsRawBlock title="Raw Execution JSON" value={safeSerialize(item)} />
            </>
          ),
        },
        {
          id: 'copy-command',
          type: 'copy',
          label: 'Copy command',
          value: item.command || '',
          disabled: !item.command,
          description: 'Execution command copied to the clipboard.',
        },
        {
          id: 'copy-output',
          type: 'copy',
          label: 'Copy raw output',
          value: rawOutput,
          description: 'Execution output copied to the clipboard.',
        },
        {
          id: 'copy-artifact-path',
          type: 'copy',
          label: 'Copy artifact path',
          value: artifactPath || '',
          hidden: !artifactPath,
          description: 'Artifact path copied to the clipboard.',
        },
        {
          id: 'artifact-details',
          type: 'panel',
          label: 'Open artifact details',
          hidden: !artifactPath,
          description: 'Review artifact metadata and storage details.',
          renderPanel: () => (
            <>
              <OpsMetaGrid items={[
                { label: 'Artifact path', value: artifactPath },
                { label: 'Captured bytes', value: formatBytes(item.output_bytes) },
                { label: 'Started', value: formatDateTime(item.started_at || item.created_at) },
                { label: 'Last output', value: item.last_output_at ? formatRelativeTime(item.last_output_at) : 'none yet' },
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
          description: 'Opening the first detected URL tied to this execution.',
          onClick: () => openInBrowser(browserUrl),
        },
        {
          id: 'copy-version',
          type: 'copy',
          label: 'Copy detected version',
          hidden: !detectedVersion,
          value: detectedVersion || '',
          description: 'Detected service version copied to the clipboard.',
        },
      ]}
    />
  )
}

export function JobsPanel({ activeTarget, selectedExecutionKey, setSelectedExecutionKey, stopExecution, loading, condensed = false, commandAllowlist }) {
  const executionItems = buildExecutionItems(activeTarget)
  const selectedItem = executionItems.find((item) => executionKey(item) === selectedExecutionKey) || executionItems[0] || null
  const activeCount = executionItems.filter(executionIsActive).length

  return (
    <Panel title={condensed ? 'Live Execution' : 'Jobs'} meta={`${activeCount} active`}>
      {!executionItems.length ? <EmptyState title="No executions" body="No jobs or approved actions have been started yet." /> : (
        <div className={condensed ? 'execution-monitor condensed' : 'execution-monitor'}>
          <div className="execution-listing">
            {executionItems.map((item) => (
              <button
                className={executionKey(item) === executionKey(selectedItem || {}) ? 'execution-row active' : 'execution-row'}
                key={executionKey(item)}
                type="button"
                onClick={() => setSelectedExecutionKey?.(executionKey(item))}
              >
                <div>
                  <strong>{cleanDisplayText(item.title, 'Execution')}</strong>
                  <span>{item.category_label} · {cleanDisplayText(item.detail, 'No detail recorded.')}</span>
                  <span className="execution-chip-row">
                    {commandIsAllowlisted(item, commandAllowlist) ? <small className="stage-chip good">auto-allowed: {commandNameFromItem(item)}</small> : null}
                    {commandLooksLikeInstall(item) ? <small className="stage-chip danger">install approval required</small> : null}
                  </span>
                </div>
                <em className={badgeClass(item.status)}>{item.status}</em>
                <small>{formatTime(item.started_at || item.created_at)}</small>
              </button>
            ))}
          </div>

          {selectedItem ? (
            <article className="execution-inspector">
              <div className="execution-inspector-head">
                <div>
                  <span className="eyebrow">{selectedItem.category_label}</span>
                  <h4>{cleanDisplayText(selectedItem.title, 'Execution')}</h4>
                  <p>{executionStatusCopy(selectedItem)}</p>
                </div>
                <div className="execution-actions">
                  <span className={badgeClass(selectedItem.status)}>{selectedItem.status}</span>
                  <button
                    className="danger-button"
                    type="button"
                    disabled={loading || !executionIsActive(selectedItem)}
                    onClick={() => stopExecution(selectedItem)}
                  >
                    Stop
                  </button>
                </div>
              </div>

              <dl className="execution-metadata">
                <div><dt>PID</dt><dd>{selectedItem.pid || 'n/a'}</dd></div>
                <div><dt>Started</dt><dd>{formatDateTime(selectedItem.started_at || selectedItem.created_at)}</dd></div>
                <div><dt>Last output</dt><dd>{selectedItem.last_output_at ? formatRelativeTime(selectedItem.last_output_at) : 'none yet'}</dd></div>
                <div><dt>Captured</dt><dd>{formatBytes(selectedItem.output_bytes)}</dd></div>
                <div><dt>Artifact</dt><dd>{cleanDisplayText(selectedItem.output_path, 'not written yet')}</dd></div>
                <div><dt>Exit</dt><dd>{executionExitLabel(selectedItem)}</dd></div>
              </dl>

              <code className="command-line">{selectedItem.command || 'No command recorded.'}</code>
              <pre className="console-tail">{selectedItem.live_output_tail || selectedItem.result_excerpt || selectedItem.error || 'No output captured yet.'}</pre>
              <ExecutionActions item={selectedItem} condensed={condensed} commandAllowlist={commandAllowlist} />

              {!condensed ? (
                <div className="execution-notes">
                  <p>{cleanDisplayText(selectedItem.parse_summary || selectedItem.summary, 'No summary recorded yet.')}</p>
                </div>
              ) : null}
            </article>
          ) : null}
        </div>
      )}
      {selectedItem ? <OpsCopyNote>The selected execution now exposes operator actions for rationale, raw I/O inspection, copy helpers, artifact details, and browser handoff when output contains a URL.</OpsCopyNote> : null}
    </Panel>
  )
}
