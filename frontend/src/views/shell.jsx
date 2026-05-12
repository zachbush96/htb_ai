import React, { useEffect, useRef, useState } from 'react'
import { Terminal } from '@xterm/xterm'
import { FitAddon } from '@xterm/addon-fit'
import '@xterm/xterm/css/xterm.css'
import { cleanDisplayText } from '../lib/app-utils'
import { EmptyState, Panel } from '../components/primitives'

function buildWsUrl(apiBase, websocketPath) {
  const base = apiBase.endsWith('/') ? apiBase.slice(0, -1) : apiBase
  const url = new URL(websocketPath, base)
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
  return url.toString()
}

function candidateKey(candidate) {
  return `${candidate.protocol}:${candidate.host}:${candidate.port}:${candidate.username || 'manual'}`
}

function formFromCandidate(candidate, fallbackIp) {
  return {
    protocol: candidate?.protocol || 'ssh',
    host: candidate?.host || fallbackIp || '',
    port: candidate?.port || (candidate?.protocol === 'telnet' ? 23 : 22),
    username: candidate?.username || '',
    password: candidate?.password || '',
    label: candidate?.label || '',
  }
}

export function ShellView({ activeTarget, apiBase, request }) {
  const terminalHostRef = useRef(null)
  const terminalRef = useRef(null)
  const fitAddonRef = useRef(null)
  const websocketRef = useRef(null)
  const [candidates, setCandidates] = useState([])
  const [tools, setTools] = useState({})
  const [selectedKey, setSelectedKey] = useState('')
  const [connectionForm, setConnectionForm] = useState(() => formFromCandidate(null, activeTarget?.ip_address))
  const [status, setStatus] = useState('idle')
  const [sessionLabel, setSessionLabel] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    websocketRef.current?.close()
    websocketRef.current = null
    setConnectionForm(formFromCandidate(null, activeTarget?.ip_address))
    setSelectedKey('')
    setCandidates([])
    setTools({})
    setSessionLabel('')
    setStatus('idle')
    setError('')
    if (!activeTarget?.id) return
    let cancelled = false
    request(`/api/targets/${activeTarget.id}/shell/candidates`)
      .then((payload) => {
        if (cancelled) return
        const nextCandidates = payload.candidates || []
        setCandidates(nextCandidates)
        setTools(payload.tools || {})
        const first = nextCandidates[0]
        if (first) {
          setSelectedKey(candidateKey(first))
          setConnectionForm(formFromCandidate(first, activeTarget.ip_address))
        }
      })
      .catch((err) => {
        if (!cancelled) setError(cleanDisplayText(String(err), 'Unable to load shell candidates.'))
      })
    return () => {
      cancelled = true
    }
  }, [activeTarget?.id])

  useEffect(() => {
    if (!terminalHostRef.current || terminalRef.current) return
    const terminal = new Terminal({
      cursorBlink: true,
      convertEol: true,
      fontFamily: '"SFMono-Regular", Consolas, "Liberation Mono", monospace',
      fontSize: 13,
      lineHeight: 1.15,
      theme: {
        background: '#020707',
        foreground: '#d7dedc',
        cursor: '#38ff2e',
        selectionBackground: '#14545d',
      },
    })
    const fitAddon = new FitAddon()
    terminal.loadAddon(fitAddon)
    terminal.open(terminalHostRef.current)
    fitAddon.fit()
    terminal.writeln('[mission-control] interactive shell ready')
    terminal.writeln('[mission-control] choose a candidate or enter connection details, then attach')
    terminal.onData((data) => {
      const socket = websocketRef.current
      if (socket?.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({ type: 'input', data }))
      }
    })
    terminalRef.current = terminal
    fitAddonRef.current = fitAddon

    const onResize = () => {
      fitAddon.fit()
      const socket = websocketRef.current
      if (socket?.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({ type: 'resize', cols: terminal.cols, rows: terminal.rows }))
      }
    }
    window.addEventListener('resize', onResize)
    return () => {
      window.removeEventListener('resize', onResize)
      websocketRef.current?.close()
      terminal.dispose()
      terminalRef.current = null
      fitAddonRef.current = null
    }
  }, [])

  function updateForm(key, value) {
    setConnectionForm((current) => ({ ...current, [key]: value }))
  }

  function selectCandidate(event) {
    const key = event.target.value
    setSelectedKey(key)
    const selected = candidates.find((candidate) => candidateKey(candidate) === key)
    if (selected) setConnectionForm(formFromCandidate(selected, activeTarget?.ip_address))
  }

  async function attachShell(event) {
    event.preventDefault()
    if (!activeTarget?.id) return
    websocketRef.current?.close()
    const terminal = terminalRef.current
    fitAddonRef.current?.fit()
    terminal?.clear()
    terminal?.writeln('[mission-control] preparing shell session...')
    setStatus('connecting')
    setError('')
    try {
      const payload = await request(`/api/targets/${activeTarget.id}/shell/sessions`, {
        method: 'POST',
        body: JSON.stringify({
          protocol: connectionForm.protocol,
          host: connectionForm.host || activeTarget.ip_address,
          port: Number(connectionForm.port),
          username: connectionForm.username || null,
          password: connectionForm.password || null,
          label: connectionForm.label || null,
          cols: terminal?.cols || 100,
          rows: terminal?.rows || 32,
        }),
      })
      setSessionLabel(payload.session?.command_display || payload.session?.label || 'interactive shell')
      const socket = new WebSocket(buildWsUrl(apiBase, payload.websocket_path))
      websocketRef.current = socket
      socket.addEventListener('open', () => {
        setStatus('attached')
        socket.send(JSON.stringify({ type: 'resize', cols: terminal?.cols || 100, rows: terminal?.rows || 32 }))
      })
      socket.addEventListener('message', (message) => {
        terminal?.write(String(message.data))
      })
      socket.addEventListener('close', () => {
        setStatus('closed')
        terminal?.writeln('\r\n[mission-control] shell session closed')
      })
      socket.addEventListener('error', () => {
        setStatus('error')
        setError('Shell websocket failed.')
      })
    } catch (err) {
      setStatus('error')
      setError(cleanDisplayText(String(err), 'Unable to attach shell.'))
      terminal?.writeln(`\r\n[mission-control] ${cleanDisplayText(String(err), 'Unable to attach shell.')}`)
    }
  }

  function detachShell() {
    websocketRef.current?.close()
    websocketRef.current = null
    setStatus('closed')
  }

  const selectedCandidate = candidates.find((candidate) => candidateKey(candidate) === selectedKey)

  return (
    <div className="shell-view">
      <Panel title="Interactive Shell" meta={status}>
        <form className="shell-connect-form" onSubmit={attachShell}>
          <label>
            Candidate
            <select value={selectedKey} onChange={selectCandidate}>
              <option value="">Manual connection</option>
              {candidates.map((candidate) => (
                <option key={candidateKey(candidate)} value={candidateKey(candidate)}>
                  {candidate.label}
                </option>
              ))}
            </select>
          </label>
          <label>
            Protocol
            <select value={connectionForm.protocol} onChange={(event) => updateForm('protocol', event.target.value)}>
              <option value="ssh">SSH</option>
              <option value="telnet">Telnet</option>
              <option value="nc">Raw TCP shell</option>
            </select>
          </label>
          <label>
            Host
            <input value={connectionForm.host} onChange={(event) => updateForm('host', event.target.value)} placeholder={activeTarget?.ip_address || 'target host'} />
          </label>
          <label>
            Port
            <input type="number" min="1" max="65535" value={connectionForm.port} onChange={(event) => updateForm('port', event.target.value)} />
          </label>
          <label>
            User
            <input value={connectionForm.username} onChange={(event) => updateForm('username', event.target.value)} placeholder="optional" />
          </label>
          <label>
            Password
            <input type="password" value={connectionForm.password} onChange={(event) => updateForm('password', event.target.value)} placeholder="optional" />
          </label>
          <button className="primary" type="submit" disabled={status === 'connecting'}>Attach</button>
          <button type="button" onClick={detachShell} disabled={!['attached', 'connecting'].includes(status)}>Detach</button>
        </form>
        {error ? <p className="error-banner compact">{error}</p> : null}
        <div className="shell-status-grid">
          <span>ssh {tools.ssh ? 'available' : 'missing'}</span>
          <span>sshpass {tools.sshpass ? 'available' : 'manual password'}</span>
          <span>telnet {tools.telnet ? 'available' : 'missing'}</span>
          <span>nc {tools.nc ? 'available' : 'missing'}</span>
        </div>
        {!candidates.length ? <EmptyState title="No shell candidates yet" body="The terminal remains available for manual SSH, telnet, or raw TCP shell attachment once evidence points to access." /> : null}
        {selectedCandidate ? <p className="shell-hint">Selected from {selectedCandidate.source}. Credential material is used only for the launch token and is not written to target state.</p> : null}
      </Panel>

      <Panel title={sessionLabel || 'Browser Terminal'} meta={activeTarget?.display_name || activeTarget?.ip_address}>
        <div className="xterm-frame" ref={terminalHostRef} />
      </Panel>
    </div>
  )
}
