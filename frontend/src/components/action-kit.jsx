import React, { useEffect, useId, useMemo, useRef, useState } from 'react'
import { cleanDisplayText, safeJson } from '../lib/app-utils'

export async function copyToClipboard(text) {
  const value = String(text ?? '')
  if (!value) return false
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(value)
    return true
  }
  const area = document.createElement('textarea')
  area.value = value
  area.setAttribute('readonly', '')
  area.style.position = 'absolute'
  area.style.left = '-9999px'
  document.body.appendChild(area)
  area.select()
  const result = document.execCommand('copy')
  area.remove()
  return result
}

export function openExternal(url) {
  if (!url) return false
  window.open(url, '_blank', 'noopener,noreferrer')
  return true
}

export function ActionMenu({ label = 'Actions', items = [], align = 'right', buttonClassName = '', menuClassName = '' }) {
  const [open, setOpen] = useState(false)
  const menuRef = useRef(null)
  const buttonId = useId()
  const normalized = useMemo(() => items.filter(Boolean), [items])

  useEffect(() => {
    if (!open) return undefined
    function handlePointer(event) {
      if (menuRef.current && !menuRef.current.contains(event.target)) {
        setOpen(false)
      }
    }
    function handleKey(event) {
      if (event.key === 'Escape') setOpen(false)
    }
    window.addEventListener('pointerdown', handlePointer)
    window.addEventListener('keydown', handleKey)
    return () => {
      window.removeEventListener('pointerdown', handlePointer)
      window.removeEventListener('keydown', handleKey)
    }
  }, [open])

  if (!normalized.length) return null

  return (
    <div className={`action-menu ${open ? 'open' : ''}`} ref={menuRef}>
      <button
        aria-controls={buttonId}
        aria-expanded={open}
        className={`action-menu-trigger ${buttonClassName}`.trim()}
        type="button"
        onClick={() => setOpen((current) => !current)}
      >
        {label}
      </button>
      {open ? (
        <div className={`action-menu-popover ${align} ${menuClassName}`.trim()} id={buttonId} role="menu">
          {normalized.map((item) => (
            <button
              className={`action-menu-item ${item.variant || ''}`.trim()}
              disabled={item.disabled}
              key={item.id || item.label}
              type="button"
              onClick={async () => {
                setOpen(false)
                await item.onSelect?.()
              }}
            >
              <strong>{item.label}</strong>
              {item.description ? <span>{item.description}</span> : null}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  )
}

export function ActionModal({ modal, onClose }) {
  useEffect(() => {
    if (!modal) return undefined
    function handleKey(event) {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handleKey)
    return () => window.removeEventListener('keydown', handleKey)
  }, [modal, onClose])

  if (!modal) return null
  const body = modal.format === 'json' ? safeJson(modal.body) : String(modal.body ?? '')

  return (
    <div className="modal-backdrop" role="presentation" onClick={(event) => event.target === event.currentTarget && onClose()}>
      <section aria-label={modal.title} className="modal-card" role="dialog" aria-modal="true">
        <div className="modal-head">
          <div>
            <span className="eyebrow">{cleanDisplayText(modal.eyebrow, 'Action detail')}</span>
            <h3>{modal.title}</h3>
            {modal.description ? <p>{modal.description}</p> : null}
          </div>
          <button className="modal-close" type="button" onClick={onClose}>Close</button>
        </div>
        {modal.meta?.length ? (
          <div className="modal-tags">
            {modal.meta.map((item) => <span className="badge info" key={item}>{item}</span>)}
          </div>
        ) : null}
        <pre className="modal-body">{body}</pre>
      </section>
    </div>
  )
}

export function useActionModal() {
  const [modal, setModal] = useState(null)
  return {
    modal,
    closeModal: () => setModal(null),
    openTextModal(title, body, options = {}) {
      setModal({
        title,
        body,
        format: 'text',
        ...options,
      })
    },
    openJsonModal(title, body, options = {}) {
      setModal({
        title,
        body,
        format: 'json',
        ...options,
      })
    },
  }
}
