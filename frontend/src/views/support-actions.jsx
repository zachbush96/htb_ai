import React, { useEffect, useState } from 'react'
import { cleanDisplayText, safeJson } from '../lib/app-utils'
import { copyToClipboard, openExternal } from '../components/action-kit'

const surfaceTone = {
  border: '1px solid rgba(107, 160, 176, 0.14)',
  borderRadius: '10px',
  background: 'rgba(255, 255, 255, 0.03)',
}

const styles = {
  card: {
    ...surfaceTone,
    display: 'grid',
    gap: '0.7rem',
    padding: '0.9rem',
  },
  header: {
    display: 'flex',
    gap: '0.8rem',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
  },
  headerBlock: {
    display: 'grid',
    gap: '0.25rem',
    minWidth: 0,
  },
  subtitle: {
    color: '#aab4b7',
    fontSize: '0.9rem',
    lineHeight: 1.4,
    overflowWrap: 'anywhere',
  },
  meta: {
    color: '#9ca9ac',
    fontSize: '0.78rem',
    letterSpacing: '0.06em',
    textTransform: 'uppercase',
  },
  menuDetails: {
    position: 'relative',
    minWidth: '9rem',
  },
  menuSummary: {
    listStyle: 'none',
    cursor: 'pointer',
    userSelect: 'none',
    padding: '0.62rem 0.82rem',
    border: '1px solid rgba(74, 255, 62, 0.28)',
    borderRadius: '8px',
    background: 'linear-gradient(180deg, rgba(14, 39, 33, 0.96), rgba(3, 17, 21, 0.96))',
    color: '#e8eee9',
    textTransform: 'uppercase',
    letterSpacing: '0.04em',
    fontSize: '0.8rem',
    whiteSpace: 'nowrap',
  },
  menuBody: {
    ...surfaceTone,
    position: 'absolute',
    right: 0,
    top: 'calc(100% + 0.45rem)',
    zIndex: 20,
    minWidth: '16rem',
    padding: '0.45rem',
    boxShadow: '0 18px 36px rgba(0, 0, 0, 0.28)',
    background: 'rgba(5, 20, 29, 0.98)',
  },
  menuButton: {
    width: '100%',
    textAlign: 'left',
    textTransform: 'none',
    letterSpacing: 0,
    padding: '0.72rem 0.82rem',
    display: 'grid',
    gap: '0.18rem',
  },
  menuDescription: {
    color: '#aab4b7',
    fontSize: '0.82rem',
    textTransform: 'none',
    letterSpacing: 0,
  },
  notice: {
    ...surfaceTone,
    marginBottom: '0.85rem',
    padding: '0.72rem 0.82rem',
    color: '#d8f6dc',
    background: 'rgba(35, 105, 38, 0.22)',
  },
  why: {
    ...surfaceTone,
    padding: '0.72rem 0.82rem',
    background: 'rgba(0, 10, 14, 0.55)',
  },
  whySummary: {
    cursor: 'pointer',
    color: '#dce7df',
    fontWeight: 700,
  },
  whyBody: {
    marginTop: '0.55rem',
    color: '#aab4b7',
    lineHeight: 1.45,
    whiteSpace: 'pre-wrap',
  },
  modalBackdrop: {
    position: 'fixed',
    inset: 0,
    zIndex: 100,
    display: 'grid',
    placeItems: 'center',
    padding: '1.4rem',
    background: 'rgba(1, 6, 8, 0.76)',
  },
  modalCard: {
    ...surfaceTone,
    width: 'min(960px, 100%)',
    maxHeight: '88vh',
    overflow: 'hidden',
    display: 'grid',
    gap: '0.9rem',
    padding: '1rem',
    background: 'linear-gradient(180deg, rgba(5, 20, 29, 0.98), rgba(3, 14, 18, 0.96))',
  },
  modalHead: {
    display: 'flex',
    justifyContent: 'space-between',
    gap: '1rem',
    alignItems: 'flex-start',
  },
  modalText: {
    margin: 0,
    color: '#aab4b7',
    lineHeight: 1.45,
  },
  modalBody: {
    margin: 0,
    overflow: 'auto',
    maxHeight: '62vh',
    padding: '0.9rem',
    border: '1px solid rgba(0, 229, 255, 0.18)',
    borderRadius: '8px',
    background: 'rgba(0, 7, 9, 0.78)',
    color: '#26ffd6',
    whiteSpace: 'pre-wrap',
    wordBreak: 'break-word',
  },
}

function detailsTitle(label) {
  return `${label} actions`
}

export function useSupportActions() {
  const [notice, setNotice] = useState('')
  const [modal, setModal] = useState(null)

  useEffect(() => {
    if (!notice) return undefined
    const timer = window.setTimeout(() => setNotice(''), 2200)
    return () => window.clearTimeout(timer)
  }, [notice])

  async function copyValue(label, value) {
    const text = String(value ?? '').trim()
    if (!text) {
      setNotice(`No ${label.toLowerCase()} available.`)
      return false
    }
    try {
      await copyToClipboard(text)
      setNotice(`${label} copied.`)
      return true
    } catch {
      setNotice(`Failed to copy ${label.toLowerCase()}.`)
      return false
    }
  }

  function openText(title, body, options = {}) {
    setModal({
      title,
      body: cleanDisplayText(body, 'No detail available.'),
      description: options.description || '',
      eyebrow: options.eyebrow || 'Support action',
    })
  }

  function openJson(title, value, options = {}) {
    setModal({
      title,
      body: safeJson(value ?? {}),
      description: options.description || '',
      eyebrow: options.eyebrow || 'Raw payload',
    })
  }

  function openUrl(label, url) {
    if (!url) {
      setNotice(`No ${label.toLowerCase()} available.`)
      return false
    }
    openExternal(url)
    setNotice(`${label} opened in a new tab.`)
    return true
  }

  return {
    notice,
    modal,
    closeModal: () => setModal(null),
    copyValue,
    openText,
    openJson,
    openUrl,
  }
}

export function SupportNotice({ notice }) {
  if (!notice) return null
  return <div style={styles.notice}>{notice}</div>
}

export function SupportActionMenu({ label = 'Actions', items = [] }) {
  const enabledItems = items.filter(Boolean)
  if (!enabledItems.length) return null

  return (
    <details style={styles.menuDetails}>
      <summary aria-label={detailsTitle(label)} style={styles.menuSummary}>{label}</summary>
      <div style={styles.menuBody}>
        {enabledItems.map((item) => (
          <button
            disabled={item.disabled}
            key={item.id || item.label}
            style={styles.menuButton}
            type="button"
            onClick={(event) => {
              event.currentTarget.closest('details')?.removeAttribute('open')
              item.onSelect?.()
            }}
          >
            <strong>{item.label}</strong>
            {item.description ? <span style={styles.menuDescription}>{item.description}</span> : null}
          </button>
        ))}
      </div>
    </details>
  )
}

export function SupportCard({ title, subtitle, meta, menuItems = [], children }) {
  return (
    <article style={styles.card}>
      <div style={styles.header}>
        <div style={styles.headerBlock}>
          {meta ? <span style={styles.meta}>{meta}</span> : null}
          <strong>{title}</strong>
          {subtitle ? <span style={styles.subtitle}>{subtitle}</span> : null}
        </div>
        <SupportActionMenu items={menuItems} />
      </div>
      {children}
    </article>
  )
}

export function SupportWhy({ title = 'Ask why', body }) {
  if (!body) return null
  return (
    <details style={styles.why}>
      <summary style={styles.whySummary}>{title}</summary>
      <div style={styles.whyBody}>{body}</div>
    </details>
  )
}

export function SupportModal({ modal, onClose }) {
  if (!modal) return null
  return (
    <div role="presentation" style={styles.modalBackdrop} onClick={(event) => event.target === event.currentTarget && onClose()}>
      <section aria-modal="true" aria-label={modal.title} role="dialog" style={styles.modalCard}>
        <div style={styles.modalHead}>
          <div style={{ display: 'grid', gap: '0.3rem' }}>
            <span style={styles.meta}>{modal.eyebrow}</span>
            <h3 style={{ margin: 0 }}>{modal.title}</h3>
            {modal.description ? <p style={styles.modalText}>{modal.description}</p> : null}
          </div>
          <button type="button" onClick={onClose}>Close</button>
        </div>
        <pre style={styles.modalBody}>{modal.body}</pre>
      </section>
    </div>
  )
}
