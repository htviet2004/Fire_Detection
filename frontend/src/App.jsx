import { useEffect, useRef, useState, useCallback } from 'react'

const SAFE = 'SAFE'
const SMOKE = 'SMOKE'
const FIRE = 'FIRE'

const API_ROOT = import.meta.env.VITE_API_ROOT ?? ''

function inferWsUrl() {
  if (import.meta.env.VITE_WS_URL) return import.meta.env.VITE_WS_URL
  const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws'
  return `${protocol}://${window.location.host}/ws/alerts/`
}

function formatTime(iso) {
  if (!iso) return '--'
  const d = new Date(iso)
  if (isNaN(d)) return '--'
  return d.toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

export default function App() {
  const [status, setStatus] = useState({ state: SAFE, confidence: 0, label: '', source: '0', updated_at: null })
  const [events, setEvents] = useState([])
  const [connected, setConnected] = useState(false)
  const [sourceInput, setSourceInput] = useState('0')
  const [videoLink, setVideoLink] = useState('')
  const [selectedVideo, setSelectedVideo] = useState(null)
  const [busy, setBusy] = useState(false)
  const [uploadBusy, setUploadBusy] = useState(false)
  const [toast, setToast] = useState('')
  const [streamNonce, setStreamNonce] = useState(0)
  const [streamError, setStreamError] = useState('')
  const [metrics, setMetrics] = useState(null)
  const [showMetrics, setShowMetrics] = useState(false)
  const [isLoading, setIsLoading] = useState(true)

  const retryTimer = useRef(null)
  const retryCount = useRef(0)
  const socketRef = useRef(null)
  const reconnectRef = useRef(null)
  const reconnectAttempts = useRef(0)
  const prevState = useRef(SAFE)

  const streamUrl = `${API_ROOT}/api/stream/?v=${streamNonce}`

  const statusClass = status.state === FIRE ? 'fire' : status.state === SMOKE ? 'smoke' : 'safe'

  const showToast = useCallback((msg) => {
    setToast(msg)
  }, [])

  useEffect(() => {
    if (!toast) return
    const t = setTimeout(() => setToast(''), 2500)
    return () => clearTimeout(t)
  }, [toast])

  useEffect(() => {
    if (status.state !== SAFE && prevState.current !== status.state) {
      showToast(`Alert: ${status.state}`)
    }
    prevState.current = status.state
  }, [status.state, showToast])

  // WebSocket
  useEffect(() => {
    const connect = () => {
      const ws = new WebSocket(inferWsUrl())
      socketRef.current = ws

      ws.onopen = () => {
        setConnected(true)
        reconnectAttempts.current = 0
      }

      ws.onclose = () => {
        setConnected(false)
        socketRef.current = null
        const delay = Math.min(1000 * Math.pow(2, reconnectAttempts.current), 30000)
        reconnectAttempts.current++
        reconnectRef.current = setTimeout(connect, delay)
      }

      ws.onerror = () => {}

      ws.onmessage = (e) => {
        try {
          const p = JSON.parse(e.data)
          switch (p.type) {
            case 'snapshot':
              if (p.status) setStatus(p.status)
              if (Array.isArray(p.events)) setEvents(p.events)
              setIsLoading(false)
              break
            case 'status_update':
              if (p.status) setStatus(p.status)
              break
            case 'event_log':
              if (p.event) {
                setEvents(prev => [p.event, ...prev].slice(0, 100))
              }
              break
            case 'metrics':
              if (p.metrics) setMetrics(p.metrics)
              break
          }
        } catch {}
      }
    }

    connect()

    const interval = setInterval(() => {
      if (socketRef.current?.readyState === WebSocket.OPEN) {
        socketRef.current.send(JSON.stringify({ type: 'get_metrics' }))
      }
    }, 5000)

    return () => {
      clearInterval(interval)
      if (reconnectRef.current) clearTimeout(reconnectRef.current)
      socketRef.current?.close()
    }
  }, [])

  const handleStreamError = useCallback(() => {
    setIsLoading(false)
    retryCount.current++
    setStreamError(`Reconnecting (${retryCount.current})...`)
    if (!retryTimer.current) {
      retryTimer.current = setTimeout(() => {
        retryTimer.current = null
        setStreamNonce(n => n + 1)
      }, 3000)
    }
  }, [])

  const handleStreamLoad = useCallback(() => {
    setIsLoading(false)
    setStreamError('')
    retryCount.current = 0
  }, [])

  const setSource = useCallback(async (src, msg) => {
    setBusy(true)
    try {
      const res = await fetch(`${API_ROOT}/api/source/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ source: src })
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(data.error || 'Failed')
      if (data.status) setStatus(data.status)
      setStreamNonce(n => n + 1)
      setStreamError('')
      showToast(msg || 'Source changed')
    } catch (e) {
      showToast(e.message)
    } finally {
      setBusy(false)
    }
  }, [API_ROOT, showToast])

  const handleApply = (e) => {
    e.preventDefault()
    const src = sourceInput.trim()
    if (src) setSource(src, `Camera: ${src}`)
  }

  const handleVideoLink = (e) => {
    e.preventDefault()
    const link = videoLink.trim()
    if (link) setSource(link, 'Video link loaded')
  }

  const handleUpload = async (e) => {
    e.preventDefault()
    if (!selectedVideo) {
      showToast('Select a video first')
      return
    }
    setUploadBusy(true)
    try {
      const form = new FormData()
      form.append('video', selectedVideo)
      const res = await fetch(`${API_ROOT}/api/upload-video/`, { method: 'POST', body: form })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(data.error || 'Upload failed')
      if (data.status) setStatus(data.status)
      setStreamNonce(n => n + 1)
      setStreamError('')
      showToast('Video loaded')
      setSelectedVideo(null)
    } catch (e) {
      showToast(e.message)
    } finally {
      setUploadBusy(false)
    }
  }

  return (
    <div className="app">
      <header className="header">
        <div className="header-left">
          <div className="logo">F</div>
          <h1>Fire Monitor</h1>
        </div>
        <div className="conn-status">
          <span className={`conn-dot ${connected ? 'on' : 'off'}`} />
          {connected ? 'Live' : 'Reconnecting'}
        </div>
      </header>

      {(status.state === FIRE || status.state === SMOKE) && (
        <div className={`alert-banner ${statusClass}`}>
          <span>{status.state === FIRE ? 'FIRE DETECTED' : 'SMOKE DETECTED'}</span>
          <span style={{ opacity: 0.7 }}>— {status.label} ({Number(status.confidence).toFixed(2)})</span>
        </div>
      )}

      {toast && <div className="toast">{toast}</div>}

      <main className="main">
        <section className="stream-section">
          <div className="stream-container">
            <img
              src={streamUrl}
              alt="Stream"
              className="stream-img"
              onError={handleStreamError}
              onLoad={handleStreamLoad}
            />
            {isLoading && (
              <div className="stream-loading">
                <div className="spinner" />
                <span>Connecting...</span>
              </div>
            )}
            <div className={`stream-status ${statusClass}`}>{status.state}</div>
            {streamError && <div className="stream-error-msg">{streamError}</div>}
          </div>

          <div className="controls">
            <form className="control-group" onSubmit={handleApply}>
              <label>Camera</label>
              <div className="control-row">
                <input
                  type="text"
                  value={sourceInput}
                  onChange={e => setSourceInput(e.target.value)}
                  placeholder="0 hoặc đường dẫn..."
                />
                <button type="submit" disabled={busy}>Apply</button>
              </div>
            </form>

            <form className="control-group" onSubmit={handleVideoLink}>
              <label>Video URL</label>
              <div className="control-row">
                <input
                  type="text"
                  value={videoLink}
                  onChange={e => setVideoLink(e.target.value)}
                  placeholder="https://... hoặc rtsp://..."
                />
                <button type="submit" disabled={busy}>Load</button>
              </div>
            </form>

            <form className="control-group" onSubmit={handleUpload}>
              <label>Upload Video</label>
              <div className="control-row">
                <input
                  type="file"
                  accept="video/*"
                  onChange={e => setSelectedVideo(e.target.files?.[0] ?? null)}
                />
                <button type="submit" disabled={uploadBusy}>
                  {uploadBusy ? '...' : 'Detect'}
                </button>
              </div>
            </form>
          </div>
        </section>

        <aside className="sidebar">
          <div className="sidebar-section">
            <h2>Status</h2>
            <div className={`status-state ${statusClass}`}>{status.state}</div>
            <dl className="status-grid">
              <div className="status-row">
                <dt>Label</dt>
                <dd>{status.label || '--'}</dd>
              </div>
              <div className="status-row">
                <dt>Confidence</dt>
                <dd>{Number(status.confidence || 0).toFixed(3)}</dd>
              </div>
              <div className="status-row">
                <dt>Updated</dt>
                <dd>{formatTime(status.updated_at)}</dd>
              </div>
              <div className="status-row">
                <dt>Source</dt>
                <dd>{status.source || '0'}</dd>
              </div>
            </dl>
          </div>

          <div className="sidebar-section">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
              <h2 style={{ margin: 0 }}>Events</h2>
              <button className={`metrics-toggle ${showMetrics ? 'active' : ''}`} onClick={() => setShowMetrics(!showMetrics)}>
                {showMetrics ? 'Hide' : 'Metrics'}
              </button>
            </div>

            {showMetrics && metrics && (
              <div className="metrics-grid">
                <div className="metric-item">
                  <div className="metric-label">FPS</div>
                  <div className="metric-value">{metrics.fps || 0}</div>
                </div>
                <div className="metric-item">
                  <div className="metric-label">Inferences</div>
                  <div className="metric-value">{metrics.inference_fps || 0}/s</div>
                </div>
                <div className="metric-item">
                  <div className="metric-label">Frames</div>
                  <div className="metric-value">{(metrics.frame_count || 0).toLocaleString()}</div>
                </div>
                <div className="metric-item">
                  <div className="metric-label">Model</div>
                  <div className="metric-value">{metrics.model_warmed_up ? 'Ready' : 'Loading'}</div>
                </div>
              </div>
            )}

            <div className="events-list">
              {events.length === 0 && <div className="empty-state">No events yet</div>}
              {events.map(ev => (
                <div key={ev.id} className={`event-item ${ev.status === FIRE ? 'fire' : ev.status === SMOKE ? 'smoke' : 'safe'}`}>
                  <div className="event-info">
                    <strong>{ev.status}</strong>
                    <span>{ev.label || '--'} · {Number(ev.confidence || 0).toFixed(2)}</span>
                  </div>
                  <div className="event-time">{formatTime(ev.created_at)}</div>
                </div>
              ))}
            </div>
          </div>
        </aside>
      </main>
    </div>
  )
}
