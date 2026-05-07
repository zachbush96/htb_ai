import React, { useMemo, useState } from 'react'
import { createRoot } from 'react-dom/client'

const cardStyle = {
  border: '1px solid #d0d7de',
  borderRadius: 10,
  padding: '1rem',
  marginBottom: '1rem',
  background: '#fff',
}

function App() {
  const [apiBase, setApiBase] = useState('http://127.0.0.1:8000')
  const [ollamaBase, setOllamaBase] = useState('http://100.102.78.116:11434')
  const [backendStatus, setBackendStatus] = useState('idle')
  const [ollamaStatus, setOllamaStatus] = useState('idle')
  const [rootPayload, setRootPayload] = useState(null)
  const [ollamaPayload, setOllamaPayload] = useState(null)
  const [lastError, setLastError] = useState('')

  const statusColor = useMemo(() => {
    if (backendStatus === 'ok' && ollamaStatus === 'ok') return '#1a7f37'
    if (backendStatus === 'error' || ollamaStatus === 'error') return '#cf222e'
    return '#9a6700'
  }, [backendStatus, ollamaStatus])

  async function checkBackend() {
    setLastError('')
    setBackendStatus('checking')
    try {
      const [healthRes, rootRes] = await Promise.all([
        fetch(`${apiBase}/healthz`),
        fetch(`${apiBase}/`),
      ])
      if (!healthRes.ok || !rootRes.ok) {
        throw new Error(`Backend returned HTTP ${healthRes.status}/${rootRes.status}`)
      }
      const rootJson = await rootRes.json()
      setRootPayload(rootJson)
      setBackendStatus('ok')
    } catch (err) {
      setBackendStatus('error')
      setLastError(String(err))
    }
  }

  async function checkOllama() {
    setLastError('')
    setOllamaStatus('checking')
    try {
      const res = await fetch(`${ollamaBase}/api/tags`)
      if (!res.ok) {
        throw new Error(`Ollama returned HTTP ${res.status}`)
      }
      const json = await res.json()
      setOllamaPayload(json)
      setOllamaStatus('ok')
    } catch (err) {
      setOllamaStatus('error')
      setLastError(String(err))
    }
  }

  return (
    <main
      style={{
        fontFamily: 'Inter, system-ui, sans-serif',
        background: '#f6f8fa',
        minHeight: '100vh',
        padding: '1.5rem',
      }}
    >
      <h1 style={{ marginTop: 0 }}>HTB Mission Control</h1>
      <p style={{ color: statusColor, fontWeight: 600 }}>
        System readiness: backend {backendStatus} / ollama {ollamaStatus}
      </p>

      <section style={cardStyle}>
        <h2 style={{ marginTop: 0 }}>1) Connection checks</h2>
        <label>
          Backend API base URL
          <input
            style={{ display: 'block', width: '100%', marginTop: 6, marginBottom: 12 }}
            value={apiBase}
            onChange={(e) => setApiBase(e.target.value.trim())}
          />
        </label>
        <button onClick={checkBackend}>Check backend</button>

        <label style={{ display: 'block', marginTop: 16 }}>
          Ollama URL (Tailscale)
          <input
            style={{ display: 'block', width: '100%', marginTop: 6, marginBottom: 12 }}
            value={ollamaBase}
            onChange={(e) => setOllamaBase(e.target.value.trim())}
          />
        </label>
        <button onClick={checkOllama}>Check Ollama</button>

        {lastError ? (
          <p style={{ color: '#cf222e', marginBottom: 0 }}>
            Last error: {lastError}
          </p>
        ) : null}
      </section>

      <section style={cardStyle}>
        <h2 style={{ marginTop: 0 }}>2) Live responses</h2>
        <h3>Backend root payload</h3>
        <pre>{rootPayload ? JSON.stringify(rootPayload, null, 2) : 'No response yet.'}</pre>

        <h3>Ollama /api/tags payload</h3>
        <pre>{ollamaPayload ? JSON.stringify(ollamaPayload, null, 2) : 'No response yet.'}</pre>
      </section>

      <section style={cardStyle}>
        <h2 style={{ marginTop: 0 }}>3) Next iteration plan</h2>
        <ol>
          <li>Wire a backend endpoint that proxies Ollama chat/generate requests.</li>
          <li>Add a prompt input + streamed output panel in this UI.</li>
          <li>Persist runs as timeline cards for fast HTB experiment loops.</li>
        </ol>
      </section>
    </main>
  )
}

createRoot(document.getElementById('root')).render(<App />)
