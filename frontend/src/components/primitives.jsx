import React from 'react'
import { percent } from '../lib/app-utils'

export function Panel({ title, meta, className = '', actions = null, children }) {
  return (
    <section className={`panel ${className}`.trim()}>
      <div className="panel-head">
        <h3>{title}</h3>
        <div className="panel-head-meta">
          {meta !== undefined && meta !== null ? <span>{meta}</span> : null}
          {actions}
        </div>
      </div>
      {children}
    </section>
  )
}

export function Metric({ label, value, tone = 'info' }) {
  return (
    <div className={`metric metric-${tone}`}>
      <strong>{value}</strong>
      <span>{label}</span>
    </div>
  )
}

export function BarChart({ rows }) {
  const max = Math.max(1, ...rows.map((row) => row.value))
  return (
    <div className="bar-chart">
      {rows.map((row) => (
        <div className="bar-row" key={row.label}>
          <span>{row.label}</span>
          <div><i className={row.tone || 'info'} style={{ width: `${percent(row.value, max)}%` }} /></div>
          <b>{row.value}</b>
        </div>
      ))}
    </div>
  )
}

export function Donut({ label, value, total, tone = 'info' }) {
  const pct = percent(value, total)
  return (
    <div className="donut-stat">
      <div className={`donut ${tone}`} style={{ '--pct': `${pct}%` }}>
        <b>{value}</b>
      </div>
      <span>{label}</span>
      <small>{pct}% of total</small>
    </div>
  )
}

export function EmptyState({ title, body }) {
  return (
    <div className="empty-state">
      <strong>{title}</strong>
      <span>{body}</span>
    </div>
  )
}
