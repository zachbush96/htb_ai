import React, { useEffect, useRef, useState } from 'react'
import { cleanDisplayText, safeJson } from '../lib/app-utils'

const menuWrapStyle = {
  position: 'relative',
  display: 'inline-flex',
  alignItems: 'center',
  zIndex: 2000,
}

const menuStyle = {
  position: 'absolute',
  top: 'calc(100% + 0.4rem)',
  right: 0,
  minWidth: '13rem',
  zIndex: 3000,
  display: 'grid',
  gap: '0.35rem',
  padding: '0.5rem',
  border: '1px solid rgba(94, 153, 171, 0.45)',
  borderRadius: '12px',
  background: 'linear-gradient(180deg, rgba(5, 20, 29, 0.98), rgba(3, 14, 18, 0.98))',
  boxShadow: '0 18px 40px rgba(0, 0, 0, 0.35)',
}

const inlineMenuStyle = {
  display: 'grid',
  gap: '0.35rem',
  marginTop: '0.45rem',
  padding: '0.5rem',
  border: '1px solid rgba(94, 153, 171, 0.35)',
  borderRadius: '12px',
  background: 'linear-gradient(180deg, rgba(5, 20, 29, 0.96), rgba(3, 14, 18, 0.96))',
}

const stackStyle = {
  display: 'flex',
  flexWrap: 'wrap',
  gap: '0.6rem',
  alignItems: 'center',
}

const noticeStyle = {
  position: 'fixed',
  right: '1rem',
  bottom: '1rem',
  zIndex: 35,
  maxWidth: '22rem',
  padding: '0.9rem 1rem',
  border: '1px solid rgba(71, 255, 38, 0.45)',
  borderRadius: '12px',
  background: 'rgba(4, 20, 18, 0.96)',
  color: '#dfffe1',
  boxShadow: '0 14px 36px rgba(0, 0, 0, 0.35)',
}

const overlayStyle = {
  position: 'fixed',
  inset: 0,
  zIndex: 40,
  display: 'grid',
  placeItems: 'center',
  padding: '2rem',
  background: 'rgba(1, 6, 9, 0.72)',
}

const dialogStyle = {
  width: 'min(56rem, 100%)',
  maxHeight: '80vh',
  overflow: 'auto',
  padding: '1.1rem',
  border: '1px solid rgba(94, 153, 171, 0.45)',
  borderRadius: '16px',
  background: 'linear-gradient(180deg, rgba(5, 20, 29, 0.99), rgba(3, 14, 18, 0.99))',
  boxShadow: '0 24px 60px rgba(0, 0, 0, 0.45)',
}

const dialogBodyStyle = {
  margin: 0,
  padding: '1rem',
  borderRadius: '12px',
  background: 'rgba(0, 10, 16, 0.88)',
  color: '#e6f7ec',
  whiteSpace: 'pre-wrap',
  overflowX: 'auto',
}

function stringValue(value, fallback = 'No data available.') {
  if (typeof value === 'string') return value.trim() || fallback
  if (value === undefined || value === null) return fallback
  return safeJson(value) || fallback
}

async function fallbackCopy(value) {
  const field = document.createElement('textarea')
  field.value = value
  field.setAttribute('readonly', 'true')
  field.style.position = 'absolute'
  field.style.left = '-9999px'
  document.body.appendChild(field)
  field.select()
  document.execCommand('copy')
  document.body.removeChild(field)
}

export async function writeClipboard(value) {
  const text = stringValue(value)
  if (navigator?.clipboard?.writeText) {
    await navigator.clipboard.writeText(text)
    return
  }
  await fallbackCopy(text)
}

export function openExternalUrl(url) {
  if (!url) return false
  window.open(url, '_blank', 'noopener,noreferrer')
  return true
}

export function jumpToPrimaryView(viewLabel) {
  const label = cleanDisplayText(viewLabel).toLowerCase()
  const match = [...document.querySelectorAll('.nav-list button')].find((button) => {
    const text = cleanDisplayText(button.textContent, '').toLowerCase()
    return text.includes(label)
  })
  if (!match) return false
  match.click()
  return true
}

export function buildWhySections(sections, fallback = 'No explanation is available yet.') {
  const rendered = sections
    .map((section) => {
      if (!section?.value) return null
      return `${section.label}\n${cleanDisplayText(section.value, '')}`
    })
    .filter(Boolean)
  return rendered.length ? rendered.join('\n\n') : fallback
}

export function buildRawBlock(title, payload) {
  return `${title}\n\n${stringValue(payload)}`
}

export function ActionMenu({ actions, label = 'Actions', compact = false }) {
  const [open, setOpen] = useState(false)
  const wrapRef = useRef(null)

  useEffect(() => {
    if (!open) return undefined
    function handlePointer(event) {
      if (!wrapRef.current?.contains(event.target)) setOpen(false)
    }
    function handleKey(event) {
      if (event.key === 'Escape') setOpen(false)
    }
    window.addEventListener('mousedown', handlePointer)
    window.addEventListener('keydown', handleKey)
    return () => {
      window.removeEventListener('mousedown', handlePointer)
      window.removeEventListener('keydown', handleKey)
    }
  }, [open])

  const filteredActions = actions.filter(Boolean)
  if (!filteredActions.length) return null

  return (
    <div ref={wrapRef} style={menuWrapStyle}>
      <button aria-expanded={open} aria-haspopup="menu" type="button" onClick={() => setOpen((current) => !current)}>
        {compact ? '•••' : label}
      </button>
      {open ? (
        <div role="menu" style={compact ? inlineMenuStyle : menuStyle}>
          {filteredActions.map((action) => (
            <button
              className={action.tone === 'danger' ? 'danger-button' : ''}
              key={action.label}
              type="button"
              disabled={action.disabled}
              onClick={() => {
                setOpen(false)
                action.onSelect?.()
              }}
            >
              {action.label}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  )
}

export function ActionBar({ children }) {
  return <div style={stackStyle}>{children}</div>
}

export function ActionDialog({ dialog, onClose }) {
  useEffect(() => {
    if (!dialog) return undefined
    function handleKey(event) {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handleKey)
    return () => window.removeEventListener('keydown', handleKey)
  }, [dialog, onClose])

  if (!dialog) return null

  return (
    <div style={overlayStyle}>
      <article style={dialogStyle}>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: '1rem', alignItems: 'center', marginBottom: '0.9rem' }}>
          <div>
            <strong>{dialog.title}</strong>
            {dialog.caption ? <div style={{ color: '#aab4b7', marginTop: '0.25rem' }}>{dialog.caption}</div> : null}
          </div>
          <button type="button" onClick={onClose}>Close</button>
        </div>
        <pre style={dialogBodyStyle}>{stringValue(dialog.body)}</pre>
      </article>
    </div>
  )
}

export function ActionNotice({ notice }) {
  if (!notice) return null
  return <div style={noticeStyle}>{notice}</div>
}

export function useActionRuntime() {
  const [dialog, setDialog] = useState(null)
  const [notice, setNotice] = useState('')
  const noticeTimerRef = useRef(null)

  useEffect(() => () => {
    if (noticeTimerRef.current) window.clearTimeout(noticeTimerRef.current)
  }, [])

  function flash(message) {
    setNotice(message)
    if (noticeTimerRef.current) window.clearTimeout(noticeTimerRef.current)
    noticeTimerRef.current = window.setTimeout(() => setNotice(''), 2400)
  }

  function closeDialog() {
    setDialog(null)
  }

  function showText(title, body, caption = '') {
    setDialog({ title, body, caption })
  }

  function showJson(title, payload, caption = '') {
    setDialog({ title, body: safeJson(payload), caption })
  }

  async function copyText(label, value) {
    await writeClipboard(value)
    flash(`${label} copied`)
  }

  async function copyJson(label, value) {
    await copyText(label, safeJson(value))
  }

  function openBrowser(url) {
    if (!openExternalUrl(url)) {
      flash('No browser endpoint available')
      return
    }
    flash(`Opened ${url}`)
  }

  function jump(label) {
    if (!jumpToPrimaryView(label)) {
      flash(`Unable to locate ${label}`)
      return
    }
    flash(`Jumped to ${label}`)
  }

  return {
    dialog,
    notice,
    closeDialog,
    showText,
    showJson,
    copyText,
    copyJson,
    openBrowser,
    jump,
    flash,
  }
}
