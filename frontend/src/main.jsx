import React from 'react'
import { createRoot } from 'react-dom/client'

function App() {
  return (
    <main style={{ fontFamily: 'sans-serif', padding: '1.5rem' }}>
      <h1>HTB Mission Control</h1>
      <p>Frontend is running.</p>
    </main>
  )
}

createRoot(document.getElementById('root')).render(<App />)
