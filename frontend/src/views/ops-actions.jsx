import React, { useState } from 'react'
import { cleanDisplayText } from '../lib/app-utils'

const actionStyles = {
  shell: {
    marginTop: '0.8rem',
    display: 'grid',
    gap: '0.6rem',
  },
  details: {
    border: '1px solid rgba(94, 153, 171, 0.27)',
    borderRadius: '10px',
    background: 'rgba(3, 14, 18, 0.55)',
    overflow: 'hidden',
  },
  summary: {
    cursor: 'pointer',
    listStyle: 'none',
    padding: '0.72rem 0.85rem',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: '1rem',
    color: '#dce7df',
    fontSize: '0.86rem',
  },
  summaryHint: {
    color: '#aab4b7',
    fontSize: '0.78rem',
  },
  body: {
    display: 'grid',
    gap: '0.75rem',
    padding: '0 0.85rem 0.85rem',
  },
  actionGrid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))',
    gap: '0.55rem',
  },
  actionButton: {
    width: '100%',
    textTransform: 'none',
    letterSpacing: '0.01em',
    fontSize: '0.83rem',
    padding: '0.62rem 0.72rem',
    minHeight: 'unset',
  },
  panel: {
    display: 'grid',
    gap: '0.7rem',
    border: '1px solid rgba(94, 153, 171, 0.27)',
    borderRadius: '10px',
    padding: '0.85rem',
    background: 'rgba(1, 10, 14, 0.72)',
  },
  panelHead: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: '0.75rem',
  },
  panelTitle: {
    margin: 0,
    fontSize: '0.94rem',
  },
  note: {
    margin: 0,
    color: '#cdd7da',
    fontSize: '0.9rem',
    lineHeight: 1.5,
  },
  muted: {
    color: '#aab4b7',
    fontSize: '0.82rem',
  },
  list: {
    margin: 0,
    paddingLeft: '1.15rem',
    color: '#dce7df',
    display: 'grid',
    gap: '0.45rem',
  },
  rawShell: {
    display: 'grid',
    gap: '0.45rem',
  },
  rawTitle: {
    fontSize: '0.78rem',
    textTransform: 'uppercase',
    letterSpacing: '0.08em',
    color: '#8ea8b2',
  },
  rawValue: {
    margin: 0,
    padding: '0.8rem',
    borderRadius: '8px',
    background: 'rgba(0, 0, 0, 0.28)',
    border: '1px solid rgba(94, 153, 171, 0.2)',
    whiteSpace: 'pre-wrap',
    overflowX: 'auto',
    maxHeight: '22rem',
    color: '#eff4ef',
  },
  metaGrid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))',
    gap: '0.65rem',
  },
  metaCard: {
    border: '1px solid rgba(94, 153, 171, 0.2)',
    borderRadius: '8px',
    padding: '0.7rem',
    background: 'rgba(2, 12, 18, 0.6)',
  },
  metaLabel: {
    display: 'block',
    color: '#8ea8b2',
    fontSize: '0.74rem',
    textTransform: 'uppercase',
    letterSpacing: '0.08em',
    marginBottom: '0.35rem',
  },
  metaValue: {
    margin: 0,
    color: '#eff4ef',
    wordBreak: 'break-word',
  },
}

function formatStructuredValue(value) {
  if (value === undefined || value === null) return ''
  if (typeof value === 'string') return value
  return JSON.stringify(value, null, 2)
}

async function writeClipboard(text) {
  const value = formatStructuredValue(text)
  if (!value) return false

  try {
    if (navigator?.clipboard?.writeText) {
      await navigator.clipboard.writeText(value)
      return true
    }
  } catch {}

  try {
    const area = document.createElement('textarea')
    area.value = value
    area.setAttribute('readonly', 'true')
    area.style.position = 'fixed'
    area.style.opacity = '0'
    document.body.appendChild(area)
    area.select()
    document.execCommand('copy')
    document.body.removeChild(area)
    return true
  } catch {}

  window.prompt('Copy this value', value)
  return false
}

function uniqueLines(values) {
  return [...new Set(values.map((value) => cleanDisplayText(value)).filter(Boolean))]
}

export function safeSerialize(value) {
  return formatStructuredValue(value) || '{}'
}

export function buildWhyItems(item, extraLines = []) {
  const lines = uniqueLines([
    item?.why,
    item?.reason,
    item?.summary,
    item?.parse_summary,
    item?.result_excerpt,
    item?.message,
    ...extraLines,
    item?.status ? `Current status: ${item.status}.` : '',
    item?.risk ? `Risk posture: ${item.risk}.` : '',
    item?.tool_available === false ? 'This step is blocked because the required tool is not currently available.' : '',
    item?.command ? 'The proposed command is available in the raw input/output drawer for operator review.' : '',
  ])
  return lines.length ? lines : ['No additional rationale was recorded for this item.']
}

export function extractFirstUrl(...values) {
  const text = values.map((value) => formatStructuredValue(value)).join('\n')
  const match = text.match(/\bhttps?:\/\/[^\s"'<>]+/i)
  return match?.[0] || null
}

export function extractArtifactPath(item) {
  return cleanDisplayText(item?.output_path || item?.artifact_path || item?.path || '', '')
}

export function extractDetectedVersion(...values) {
  const text = cleanDisplayText(values.map((value) => formatStructuredValue(value)).join(' '), '')
  const patterns = [
    /\b([A-Za-z][A-Za-z0-9+._/-]*(?: [A-Za-z][A-Za-z0-9+._/-]*){0,3} \d+(?:\.\d+){1,4}(?:[-_ ][A-Za-z0-9.]+)*)\b/,
    /\b(v?\d+(?:\.\d+){1,4}(?:[-_][A-Za-z0-9.]+)*)\b/,
  ]
  for (const pattern of patterns) {
    const match = text.match(pattern)
    if (match?.[1]) return match[1]
  }
  return null
}

export function openInBrowser(url) {
  if (!url) return
  window.open(url, '_blank', 'noopener,noreferrer')
}

export function OpsCopyNote({ children }) {
  return <p style={actionStyles.note}>{children}</p>
}

export function OpsWhyList({ items }) {
  return (
    <ul style={actionStyles.list}>
      {items.map((item, index) => <li key={`${item}-${index}`}>{item}</li>)}
    </ul>
  )
}

export function OpsMetaGrid({ items }) {
  const filtered = items.filter((item) => cleanDisplayText(item?.value, '') || item?.value === 0)
  if (!filtered.length) return null
  return (
    <div style={actionStyles.metaGrid}>
      {filtered.map((item) => (
        <div key={item.label} style={actionStyles.metaCard}>
          <span style={actionStyles.metaLabel}>{item.label}</span>
          <p style={actionStyles.metaValue}>{cleanDisplayText(String(item.value), 'n/a')}</p>
        </div>
      ))}
    </div>
  )
}

export function OpsRawBlock({ title, value, empty = 'No data recorded.' }) {
  const text = formatStructuredValue(value)
  return (
    <div style={actionStyles.rawShell}>
      <strong style={actionStyles.rawTitle}>{title}</strong>
      <pre style={actionStyles.rawValue}>{text || empty}</pre>
    </div>
  )
}

export function OpsActionMenu({ itemLabel = 'item', actions }) {
  const availableActions = actions.filter((action) => !action.hidden)
  const [activePanelId, setActivePanelId] = useState(null)
  const [notice, setNotice] = useState('')
  const activePanel = availableActions.find((action) => action.id === activePanelId && action.type === 'panel') || null

  async function handleAction(action) {
    if (action.disabled) return
    if (action.type === 'panel') {
      setActivePanelId((current) => current === action.id ? null : action.id)
      setNotice(action.description || '')
      return
    }

    if (action.type === 'copy') {
      const copied = await writeClipboard(action.value)
      setNotice(copied ? `${action.label} copied.` : `Copy helper opened for ${action.label.toLowerCase()}.`)
      return
    }

    if (action.type === 'open') {
      action.onClick?.()
      setNotice(action.description || `${action.label} opened.`)
      return
    }

    await action.onClick?.()
    setNotice(action.description || `${action.label} complete.`)
  }

  if (!availableActions.length) return null

  return (
    <div style={actionStyles.shell}>
      <details style={actionStyles.details}>
        <summary style={actionStyles.summary}>
          <strong>Actions</strong>
          <span style={actionStyles.summaryHint}>{notice || `Context tools for this ${itemLabel}`}</span>
        </summary>
        <div style={actionStyles.body}>
          <div style={actionStyles.actionGrid}>
            {availableActions.map((action) => (
              <button
                key={action.id}
                type="button"
                style={actionStyles.actionButton}
                className={action.tone === 'danger' ? 'danger-button' : ''}
                disabled={action.disabled}
                onClick={() => handleAction(action)}
              >
                {action.label}
              </button>
            ))}
          </div>

          {activePanel ? (
            <div style={actionStyles.panel}>
              <div style={actionStyles.panelHead}>
                <h5 style={actionStyles.panelTitle}>{activePanel.panelTitle || activePanel.label}</h5>
                <button type="button" style={actionStyles.actionButton} onClick={() => setActivePanelId(null)}>Hide</button>
              </div>
              {activePanel.renderPanel?.()}
            </div>
          ) : null}
        </div>
      </details>
    </div>
  )
}
