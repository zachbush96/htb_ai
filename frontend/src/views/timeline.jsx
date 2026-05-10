import React from 'react'
import { cleanDisplayText, formatDateTime, formatTime } from '../lib/app-utils'
import { EmptyState, Panel } from '../components/primitives'
import { buildWhyItems, extractArtifactPath, extractFirstUrl, openInBrowser, OpsActionMenu, OpsMetaGrid, OpsRawBlock, OpsWhyList, safeSerialize } from './ops-actions'

function firstRelatedId(entry) {
  const candidates = [entry?.data?.job_id, entry?.data?.action_id, entry?.data?.target_id, entry?.id]
  return candidates.find(Boolean) || null
}

function TimelineActions({ entry }) {
  const browserUrl = extractFirstUrl(entry.message, entry.data)
  const artifactPath = extractArtifactPath(entry.data)
  const relatedId = firstRelatedId(entry)

  return (
    <OpsActionMenu
      itemLabel="timeline event"
      actions={[
        {
          id: 'ask-why',
          type: 'panel',
          label: 'Ask why',
          description: 'Review the operational meaning of this event.',
          renderPanel: () => (
            <>
              <OpsWhyList items={buildWhyItems(entry, [
                entry.type ? `Event type ${entry.type} recorded at ${formatDateTime(entry.timestamp_utc)}.` : '',
                relatedId ? `Primary related identifier: ${relatedId}.` : '',
              ])} />
              <OpsMetaGrid items={[
                { label: 'Event type', value: entry.type || entry.event_type || 'event' },
                { label: 'Recorded', value: formatDateTime(entry.timestamp_utc) },
                { label: 'Related id', value: relatedId || 'n/a' },
              ]} />
            </>
          ),
        },
        {
          id: 'raw-io',
          type: 'panel',
          label: 'View raw input/output',
          description: 'Inspect the raw timeline payload and event metadata.',
          renderPanel: () => (
            <>
              <OpsRawBlock title="Event Message" value={entry.message} />
              <OpsRawBlock title="Event Data JSON" value={safeSerialize(entry.data || {})} />
              <OpsRawBlock title="Full Event JSON" value={safeSerialize(entry)} />
            </>
          ),
        },
        {
          id: 'copy-event-json',
          type: 'copy',
          label: 'Copy event JSON',
          value: safeSerialize(entry),
          description: 'Timeline event JSON copied to the clipboard.',
        },
        {
          id: 'copy-related-id',
          type: 'copy',
          label: 'Copy related id',
          hidden: !relatedId,
          value: relatedId || '',
          description: 'Primary related identifier copied to the clipboard.',
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
          description: 'Review artifact path metadata referenced by this event.',
          renderPanel: () => (
            <>
              <OpsMetaGrid items={[
                { label: 'Artifact path', value: artifactPath },
                { label: 'Event id', value: entry.id || 'n/a' },
                { label: 'Event type', value: entry.type || entry.event_type || 'event' },
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
          description: 'Opening the first detected URL from this timeline event.',
          onClick: () => openInBrowser(browserUrl),
        },
      ]}
    />
  )
}

export function TimelinePanel({ entries, className = '' }) {
  return (
    <Panel title="Mission Timeline" className={className}>
      <div className="timeline">
        {entries.map((entry, index) => (
          <article key={entry.id || `${entry.timestamp_utc}-${index}`}>
            <time>{formatTime(entry.timestamp_utc)}</time>
            <b>{index + 1}</b>
            <strong>{cleanDisplayText(entry.type || entry.event_type, 'event')}</strong>
            <span>{cleanDisplayText(entry.message, 'No message recorded.')}</span>
            <small>{formatDateTime(entry.timestamp_utc)}</small>
            <TimelineActions entry={entry} />
          </article>
        ))}
        {!entries.length ? <EmptyState title="No timeline yet" body="Target log entries will appear here." /> : null}
      </div>
    </Panel>
  )
}
