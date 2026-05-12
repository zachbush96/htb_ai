import React from 'react'
import { badgeClass, cleanDisplayText, commandIsAllowlisted, commandLooksLikeInstall, commandNameFromItem, stageLabel } from '../lib/app-utils'
import { EmptyState, Panel } from '../components/primitives'
import { buildWhyItems, extractDetectedVersion, extractFirstUrl, openInBrowser, OpsActionMenu, OpsCopyNote, OpsMetaGrid, OpsRawBlock, OpsWhyList, safeSerialize } from './ops-actions'

function ApprovalActions({ item, commandAllowlist }) {
  const browserUrl = extractFirstUrl(item.command, item.reason, item.summary)
  const detectedVersion = extractDetectedVersion(item.label, item.reason, item.summary, item.command)
  const allowlisted = commandIsAllowlisted(item, commandAllowlist)
  const installGated = commandLooksLikeInstall(item)

  return (
    <OpsActionMenu
      itemLabel="approval"
      actions={[
        {
          id: 'ask-why',
          type: 'panel',
          label: 'Ask why',
          description: 'Review why this action is in the queue.',
          renderPanel: () => (
            <>
              <OpsWhyList items={buildWhyItems(item, [
                allowlisted ? `${commandNameFromItem(item)} is on the operator command allowlist for routine execution review.` : '',
                installGated ? 'Software installation remains approval-gated even when the launcher command is allowlisted.' : '',
                item.tool_available ? 'The required tool is available for immediate operator approval.' : 'The command binary is not currently detected, but the operator can still approve or deny the action from this queue.',
                item.status === 'blocked' ? 'This action needs operator attention before it can run.' : '',
              ])} />
              <OpsMetaGrid items={[
                { label: 'Status', value: item.status || 'unknown' },
                { label: 'Risk', value: item.risk || 'review' },
                { label: 'Tool ready', value: item.tool_available ? 'yes' : 'no' },
                { label: 'Allowlist', value: allowlisted ? 'auto-allowed/default' : 'manual review' },
                { label: 'Install gate', value: installGated ? 'approval required' : 'not detected' },
              ]} />
            </>
          ),
        },
        {
          id: 'raw-io',
          type: 'panel',
          label: 'View raw input/output',
          description: 'Inspect the raw action proposal and serialized item payload.',
          renderPanel: () => (
            <>
              <OpsRawBlock title="Command Input" value={item.command} empty="No command recorded." />
              <OpsRawBlock title="Raw Approval JSON" value={safeSerialize(item)} />
            </>
          ),
        },
        {
          id: 'copy-command',
          type: 'copy',
          label: 'Copy command',
          value: item.command || '',
          disabled: !item.command,
          description: 'Command copied to the clipboard.',
        },
        {
          id: 'copy-json',
          type: 'copy',
          label: 'Copy action JSON',
          value: safeSerialize(item),
          description: 'Serialized approval JSON copied to the clipboard.',
        },
        {
          id: 'open-browser',
          type: 'open',
          label: 'Open in browser',
          hidden: !browserUrl,
          description: 'Opening the first detected URL from this action.',
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

export function ApprovalsPanel({ approvalQueue, loading, decideAction, removeAction, commandAllowlist }) {
  return (
    <Panel title="Pending Approvals" meta={approvalQueue.length}>
      {approvalQueue.length ? (
        <div className="approval-list">
          {approvalQueue.map((item) => (
            <article key={item.id}>
              <div>
                <strong>{cleanDisplayText(item.label, 'Pending action')}</strong>
                <span>{cleanDisplayText(item.reason, 'No reason provided.')}</span>
                <div className="approval-stage-row">
                  <span className="stage-chip">{stageLabel(item.stage)}</span>
                  <span className="stage-chip muted">{item.source === 'operator_prompt' ? 'operator requested' : 'playbook queued'}</span>
                  {commandIsAllowlisted(item, commandAllowlist) ? <span className="stage-chip good">auto-allowed: {commandNameFromItem(item)}</span> : null}
                  {commandLooksLikeInstall(item) ? <span className="stage-chip danger">install approval required</span> : null}
                  {item.tool_available === false ? <span className="stage-chip muted">binary not found</span> : null}
                </div>
                {item.mindset ? <small className="approval-mindset">{cleanDisplayText(item.mindset, '')}</small> : null}
                <code>{item.command}</code>
                <ApprovalActions item={item} commandAllowlist={commandAllowlist} />
              </div>
              <em className={badgeClass(item.risk)}>{item.risk}</em>
              <div className="approval-actions">
                <button className="primary" type="button" disabled={loading || !['pending_approval', 'blocked'].includes(item.status)} onClick={() => decideAction(item.id, 'approve')}>Approve & Run</button>
                <button className="deny" type="button" disabled={loading || !['pending_approval', 'blocked'].includes(item.status)} onClick={() => decideAction(item.id, 'deny')}>Deny</button>
                <button type="button" disabled={loading || item.status === 'running'} onClick={() => removeAction(item.id)}>Remove</button>
              </div>
            </article>
          ))}
        </div>
      ) : <EmptyState title="Queue clear" body="No actions are waiting for approval." />}
      {approvalQueue.length ? <OpsCopyNote>Allowlisted commands are marked as auto-allowed/default for operator scanning, but queued terminal actions still require approval. Software installation remains approval-gated, and approval controls stay available even when the command binary is missing.</OpsCopyNote> : null}
    </Panel>
  )
}
