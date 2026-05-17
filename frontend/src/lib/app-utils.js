export const NAV_ITEMS = [
  { id: 'conversation', label: 'Conversation', icon: 'CN' },
  { id: 'progress', label: 'Progress', icon: 'PG' },
  { id: 'dashboard', label: 'Dashboard', icon: 'DB' },
  { id: 'targets', label: 'Targets', icon: 'TG' },
  { id: 'timeline', label: 'Timeline', icon: 'TL' },
  { id: 'approvals', label: 'Approvals', icon: 'AP' },
  { id: 'jobs', label: 'Jobs', icon: 'JB' },
  { id: 'shell', label: 'Shell', icon: 'SH' },
  { id: 'loot', label: 'Loot', icon: 'LT' },
  { id: 'credentials', label: 'Credentials', icon: 'CR' },
  { id: 'reports', label: 'Reports', icon: 'RP' },
  { id: 'team', label: 'Team', icon: 'TM' },
  { id: 'settings', label: 'Settings', icon: 'ST' },
]

export const DEFAULT_COMMAND_ALLOWLIST = [
  'curl',
  'dig',
  'enum4linux-ng',
  'feroxbuster',
  'nmap',
  'ffuf',
  'gobuster',
  'dirb',
  'smbclient',
  'enum4linux',
  'nikto',
  'whatweb',
  'smbmap',
  'ldapsearch',
  'snmpwalk',
  'whatweb',
  'wget',
]

export const DEFAULT_SETTINGS = {
  refreshSeconds: 4,
  chartMode: 'counts',
  tableDensity: 'comfortable',
  autoSelectLatest: true,
  commandAllowlist: DEFAULT_COMMAND_ALLOWLIST,
}

export function inferDefaultApiBase() {
  if (typeof window === 'undefined') return 'http://127.0.0.1:8000'
  const isLocalVite = ['127.0.0.1', 'localhost'].includes(window.location.hostname) && /^517\d$/.test(window.location.port)
  if (isLocalVite) return 'http://127.0.0.1:8000'
  return window.location.origin
}

export function loadUiSettings() {
  try {
    const stored = JSON.parse(window.localStorage.getItem('htbmc-ui-settings') || '{}')
    return {
      ...DEFAULT_SETTINGS,
      ...stored,
      commandAllowlist: normalizeCommandAllowlist(stored.commandAllowlist || DEFAULT_SETTINGS.commandAllowlist),
    }
  } catch {
    return DEFAULT_SETTINGS
  }
}

export function normalizeCommandAllowlist(commands = []) {
  return [...new Set((Array.isArray(commands) ? commands : [])
    .map((item) => String(item || '').trim().toLowerCase())
    .filter((item) => /^[a-z0-9][a-z0-9._+-]*$/.test(item)))]
    .sort((left, right) => left.localeCompare(right))
}

export function commandAllowlistFromRuntime(runtimeSettings, fallback = DEFAULT_COMMAND_ALLOWLIST) {
  return normalizeCommandAllowlist(runtimeSettings?.llm?.command_allowlist || fallback)
}

export function commandNameFromItem(item) {
  const explicit = cleanDisplayText(item?.binary || '', '')
  if (explicit) return explicit.split(/[\/\s]+/).filter(Boolean).pop().toLowerCase()
  const command = cleanDisplayText(item?.command || '', '')
  const match = command.match(/^\s*(?:sudo\s+)?(?:env\s+)?([^\s]+)/i)
  if (!match) return ''
  return match[1].split('/').filter(Boolean).pop().toLowerCase()
}

export function commandIsAllowlisted(item, allowlist = DEFAULT_COMMAND_ALLOWLIST) {
  const commandName = commandNameFromItem(item)
  return Boolean(commandName && normalizeCommandAllowlist(allowlist).includes(commandName))
}

export function commandLooksLikeInstall(item) {
  const text = cleanDisplayText(`${item?.label || ''} ${item?.reason || ''} ${item?.command || ''}`, '').toLowerCase()
  return /\b(apt|apt-get|apk|yum|dnf|brew|pip3?|npm|pnpm|yarn|gem)\s+(?:.*\s)?install\b/.test(text)
    || /\binstall(?:ing|ation)?\b/.test(text)
}

export function badgeClass(value) {
  const normalized = String(value || '').toLowerCase()
  if (['ready', 'completed', 'enumerated', 'informational', 'valid', 'safe', 'low'].includes(normalized)) return 'badge good'
  if (['running', 'queued', 'approved', 'stopping', 'initial_enumeration', 'pending_approval', 'action_approved', 'agent_action_running', 'awaiting_approval', 'medium'].includes(normalized)) return 'badge warn'
  if (['stopped'].includes(normalized)) return 'badge info'
  if (['error', 'failed', 'enumeration_failed', 'denied', 'blocked', 'high', 'critical'].includes(normalized)) return 'badge danger'
  return 'badge info'
}

export function riskClass(value) {
  const normalized = String(value || '').toLowerCase()
  if (['high', 'critical', 'danger'].includes(normalized)) return 'danger'
  if (['medium', 'warn', 'warning'].includes(normalized)) return 'warn'
  return 'good'
}

export function stageLabel(value) {
  const normalized = String(value || 'general').replace(/[_-]+/g, ' ').trim()
  if (!normalized) return 'general'
  return normalized
}

export function sortApprovalQueue(items = []) {
  const statusRank = { pending_approval: 0, blocked: 1 }
  return [...items].sort((left, right) => {
    const leftStatus = statusRank[left?.status] ?? 9
    const rightStatus = statusRank[right?.status] ?? 9
    if (leftStatus !== rightStatus) return leftStatus - rightStatus
    const leftPriority = Number(left?.priority ?? 50)
    const rightPriority = Number(right?.priority ?? 50)
    if (leftPriority !== rightPriority) return leftPriority - rightPriority
    const leftCreated = String(left?.created_at || '')
    const rightCreated = String(right?.created_at || '')
    return leftCreated.localeCompare(rightCreated)
  })
}

export function formatTime(value) {
  if (!value) return '--:--:--'
  try {
    return new Date(value).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
  } catch {
    return value
  }
}

export function formatDateTime(value) {
  if (!value) return 'n/a'
  try {
    return new Date(value).toLocaleString()
  } catch {
    return value
  }
}

export function formatRelativeTime(value) {
  if (!value) return 'no activity yet'
  const deltaMs = Date.now() - new Date(value).getTime()
  if (Number.isNaN(deltaMs)) return value
  const seconds = Math.max(0, Math.round(deltaMs / 1000))
  if (seconds < 2) return 'just now'
  if (seconds < 60) return `${seconds}s ago`
  const minutes = Math.round(seconds / 60)
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.round(minutes / 60)
  return `${hours}h ago`
}

export function formatBytes(value) {
  const amount = Number(value || 0)
  if (!amount) return '0 B'
  if (amount < 1024) return `${amount} B`
  if (amount < 1024 * 1024) return `${(amount / 1024).toFixed(1)} KB`
  return `${(amount / (1024 * 1024)).toFixed(1)} MB`
}

export function serviceRisk(service) {
  const text = `${service.service || ''} ${service.detail || ''}`.toLowerCase()
  if (text.includes('tomcat') || text.includes('ajp') || text.includes('mysql')) return text.includes('mysql') ? 'medium' : 'high'
  if (text.includes('http') || text.includes('redis')) return 'low'
  return 'info'
}

export function percent(value, total) {
  if (!total) return 0
  return Math.max(0, Math.min(100, Math.round((value / total) * 100)))
}

export function stripHtml(value) {
  return String(value || '')
    .replace(/<style[\s\S]*?<\/style>/gi, ' ')
    .replace(/<script[\s\S]*?<\/script>/gi, ' ')
    .replace(/<br\s*\/?>/gi, '\n')
    .replace(/<\/(p|div|li|h[1-6]|tr|section|article)>/gi, '\n')
    .replace(/<[^>]+>/g, ' ')
}

export function decodeEntities(value) {
  return value
    .replace(/&nbsp;/gi, ' ')
    .replace(/&amp;/gi, '&')
    .replace(/&lt;/gi, '<')
    .replace(/&gt;/gi, '>')
    .replace(/&quot;/gi, '"')
    .replace(/&#39;/gi, "'")
}

export function cleanDisplayText(value, fallback = '') {
  const text = decodeEntities(stripHtml(value))
    .replace(/\r/g, '')
    .replace(/[ \t]+\n/g, '\n')
    .replace(/\n{3,}/g, '\n\n')
    .replace(/[ \t]{2,}/g, ' ')
    .trim()
  return text || fallback
}

export function cleanSummaryText(value, fallback = '') {
  const text = cleanDisplayText(value, fallback)
    .replace(/(?:(?<=\s)|(?<=^))\/(?:(?=\s)|(?=$))/g, '. ')
    .replace(/\s{2,}/g, ' ')
    .trim()
  const parts = text.split(/\.\s+/).map((part) => part.trim()).filter(Boolean)
  const deduped = parts.filter((part, index) => index === 0 || part.toLowerCase() !== parts[index - 1].toLowerCase())
  return deduped.join('. ') || fallback
}

export function buildExecutionItems(activeTarget) {
  const jobs = (activeTarget?.jobs || []).map((job) => ({
    ...job,
    execution_kind: 'job',
    category_label: 'Job',
    title: job.label || 'Job',
    detail: 'Baseline or follow-up scan',
  }))
  const actions = (activeTarget?.agent_actions || [])
    .filter((action) => !['informational', 'pending_approval', 'blocked', 'denied', 'removed'].includes(action.status))
    .map((action) => ({
      ...action,
      execution_kind: 'action',
      category_label: 'Action',
      title: action.label || 'Approved action',
      detail: action.reason || 'Approved command execution',
    }))
  const llmCalls = (activeTarget?.llm_calls || []).map((call) => ({
    ...call,
    execution_kind: 'llm',
    category_label: call.kind === 'planner' ? 'Planner LLM' : 'LLM',
    title: call.title || (call.kind === 'planner' ? 'Planner LLM decision' : 'Operator LLM request'),
    detail: call.detail || call.operator_prompt || 'Recorded prompt and response',
  }))
  return [...jobs, ...actions, ...llmCalls].sort((left, right) => {
    const rightTime = right.started_at || right.updated_at || right.created_at || ''
    const leftTime = left.started_at || left.updated_at || left.created_at || ''
    return rightTime.localeCompare(leftTime)
  })
}

export function executionIsActive(item) {
  return ['queued', 'approved', 'running', 'stopping'].includes(item?.status)
}

export function executionKey(item) {
  return `${item.execution_kind}:${item.id}`
}

export function executionStatusCopy(item) {
  if (!item) return 'No execution selected.'
  if (item.execution_kind === 'llm') {
    if (item.status === 'running') return 'Waiting for the model response.'
    if (item.status === 'completed' && item.model_error) return 'Model call failed and a local fallback response was recorded instead.'
    if (item.status === 'completed') return 'Full prompt and response were recorded for troubleshooting.'
    if (item.status === 'failed') return 'LLM request failed before a usable response was recorded.'
  }
  if (item.status === 'queued') return 'Queued and waiting for the worker thread.'
  if (item.status === 'approved') return 'Approved and about to start.'
  if (item.status === 'running') {
    return item.last_output_at
      ? `Streaming output, last activity ${formatRelativeTime(item.last_output_at)}.`
      : 'Process is running but has not produced output yet.'
  }
  if (item.status === 'stopping') return 'Stop requested. Waiting for the process to exit.'
  if (item.status === 'stopped') return 'Stopped by the operator.'
  if (item.status === 'completed') return 'Completed successfully.'
  if (item.status === 'failed') return 'Exited with an error.'
  return cleanDisplayText(item.status, 'unknown state')
}

export function objectiveTone(value) {
  const normalized = String(value || '').toLowerCase()
  if (['owned', 'privesc', 'post-access'].includes(normalized)) return 'good'
  if (['initial-access', 'cred-hunting'].includes(normalized)) return 'warn'
  return 'info'
}

export function formatObjectiveLabel(value) {
  return cleanDisplayText(String(value || 'recon').replace(/[_-]+/g, ' '), 'recon')
}

export function executionExitLabel(item) {
  if (!item) return 'n/a'
  if (item.return_code !== null && item.return_code !== undefined) return item.return_code
  if (item.termination_reason) return item.termination_reason
  if (item.status === 'completed') return 0
  if (item.status === 'stopped') return 'stopped'
  if (item.status === 'failed') return 'error'
  return 'running'
}

export function findCredentialHints(activeTarget) {
  const haystack = [
    ...(activeTarget?.observations || []).map((item) => cleanDisplayText(`${item.title || ''} ${item.summary || ''}`)),
    ...(activeTarget?.agent_actions || []).map((item) => cleanDisplayText(`${item.label || ''} ${item.summary || ''} ${item.result_excerpt || ''}`)),
  ].join('\n')
  const patterns = [
    /(?:user(?:name)?|login)\s*[:=]\s*([A-Za-z0-9._@-]{3,})/gi,
    /(?:pass(?:word)?|pwd)\s*[:=]\s*([^\s'"<>]{4,})/gi,
    /(?:token|api[_-]?key|secret)\s*[:=]\s*([A-Za-z0-9._:-]{8,})/gi,
  ]
  return patterns.flatMap((pattern) => [...haystack.matchAll(pattern)].map((match) => match[0])).slice(0, 12)
}

export function summarizeContextCounts(counts = {}) {
  const items = [
    ['services', 'services'],
    ['findings', 'findings'],
    ['observations', 'observations'],
    ['pending_actions', 'actions'],
    ['timeline', 'timeline'],
    ['context_blocks', 'notes'],
  ]
    .filter(([key]) => counts?.[key])
    .map(([key, label]) => `${counts[key]} ${label}`)
  return items.join(' · ') || 'light context'
}

export function safeJson(value) {
  return JSON.stringify(value, null, 2)
}

export function normalizeError(err) {
  return cleanDisplayText(String(err), 'Unknown error')
}

export function firstHttpUrl(service, ipAddress) {
  const port = Number(service?.port || 0)
  if (!ipAddress || !port) return null
  const serviceName = String(service?.service || '').toLowerCase()
  const tunnel = String(service?.tunnel || '').toLowerCase()
  const isWeb = serviceName.includes('http') || tunnel === 'ssl' || [80, 443, 8080, 8000, 8443, 5357, 8180].includes(port)
  if (!isWeb) return null
  const scheme = serviceName === 'https' || tunnel === 'ssl' || [443, 8443].includes(port) ? 'https' : 'http'
  if ((scheme === 'http' && port === 80) || (scheme === 'https' && port === 443)) {
    return `${scheme}://${ipAddress}`
  }
  return `${scheme}://${ipAddress}:${port}`
}
