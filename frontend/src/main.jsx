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
  const [lastError, setLastError] = useState('')
  const [targetIp, setTargetIp] = useState('')
  const [sessionData, setSessionData] = useState(null)
  const [prompt, setPrompt] = useState('Run initial safe recon recommendations.')
  const [llmData, setLlmData] = useState(null)

  const statusColor = useMemo(() => {
    if (backendStatus === 'ok' && ollamaStatus === 'ok') return '#1a7f37'
    if (backendStatus === 'error' || ollamaStatus === 'error') return '#cf222e'
    return '#9a6700'
  }, [backendStatus, ollamaStatus])

  async function checkBackend() {
    setLastError('')
    setBackendStatus('checking')
    try {
      const healthRes = await fetch(`${apiBase}/healthz`)
      if (!healthRes.ok) throw new Error(`Backend returned HTTP ${healthRes.status}`)
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
      if (!res.ok) throw new Error(`Ollama returned HTTP ${res.status}`)
      setOllamaStatus('ok')
    } catch (err) {
      setOllamaStatus('error')
      setLastError(String(err))
    }
  }

  async function startTargetSession(e) {
    e.preventDefault()
    setLastError('')
    try {
      const res = await fetch(`${apiBase}/api/targets/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ip_address: targetIp }),
      })
      const json = await res.json()
      if (!res.ok) throw new Error(json.detail || 'Failed to start target session')
      setSessionData(json)
    } catch (err) {
      setLastError(String(err))
    }
  }

  async function submitPrompt(e) {
    e.preventDefault()
    setLastError('')
    try {
      const res = await fetch(`${apiBase}/api/llm/interact`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ip_address: targetIp, prompt }),
      })
      const json = await res.json()
      if (!res.ok) throw new Error(json.detail || 'Failed to prompt LLM')
      setLlmData(json)
    } catch (err) {
      setLastError(String(err))
    }
  }

  return (
    <main style={{ fontFamily: 'Inter, system-ui, sans-serif', background: '#f6f8fa', minHeight: '100vh', padding: '1.5rem' }}>
      <h1 style={{ marginTop: 0 }}>HTB Mission Control</h1>
      <p style={{ color: statusColor, fontWeight: 600 }}>System readiness: backend {backendStatus} / ollama {ollamaStatus}</p>

      <section style={cardStyle}>
        <h2 style={{ marginTop: 0 }}>Connection checks</h2>
        <input style={{ display: 'block', width: '100%', marginBottom: 8 }} value={apiBase} onChange={(e) => setApiBase(e.target.value.trim())} />
        <button onClick={checkBackend}>Check backend</button>
        <input style={{ display: 'block', width: '100%', marginTop: 12, marginBottom: 8 }} value={ollamaBase} onChange={(e) => setOllamaBase(e.target.value.trim())} />
        <button onClick={checkOllama}>Check Ollama</button>
      </section>

      <section style={cardStyle}>
        <h2 style={{ marginTop: 0 }}>Target session</h2>
        <form onSubmit={startTargetSession}>
          <input style={{ display: 'block', width: '100%', marginBottom: 8 }} placeholder='Target IP (e.g. 10.10.11.42)' value={targetIp} onChange={(e) => setTargetIp(e.target.value)} required />
          <button type='submit'>Start target process</button>
        </form>
      </section>

      <section style={cardStyle}>
        <h2 style={{ marginTop: 0 }}>LLM interaction</h2>
        <form onSubmit={submitPrompt}>
          <textarea style={{ display: 'block', width: '100%', minHeight: 100, marginBottom: 8 }} value={prompt} onChange={(e) => setPrompt(e.target.value)} />
          <button type='submit'>Send prompt</button>
        </form>
      </section>

      {lastError ? <p style={{ color: '#cf222e' }}>Last error: {lastError}</p> : null}
      <section style={cardStyle}><h3>Session response</h3><pre>{sessionData ? JSON.stringify(sessionData, null, 2) : 'No target session yet.'}</pre></section>
      <section style={cardStyle}><h3>LLM response</h3><pre>{llmData ? JSON.stringify(llmData, null, 2) : 'No prompt response yet.'}</pre></section>
    </main>
  )
}

createRoot(document.getElementById('root')).render(<App />)
