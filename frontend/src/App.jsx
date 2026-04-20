import { useEffect, useRef, useState } from 'react'
import MJPEGStream from './MJPEGStream'

const SAFE = 'SAFE'
const SMOKE = 'SMOKE DETECTED'
const FIRE = 'FIRE ALERT'

const API_ROOT = import.meta.env.VITE_API_ROOT ?? ''

function inferWsUrl() {
  if (import.meta.env.VITE_WS_URL) {
    return import.meta.env.VITE_WS_URL
  }

  const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws'
  return `${protocol}://${window.location.host}/ws/alerts/`
}

function formatTimestamp(isoTime) {
  if (!isoTime) {
    return '--'
  }

  const date = new Date(isoTime)
  if (Number.isNaN(date.getTime())) {
    return '--'
  }

  return date.toLocaleString('vi-VN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

function App() {
  const [sourceInput, setSourceInput] = useState('0')
  const [videoLinkInput, setVideoLinkInput] = useState('')
  const [selectedVideo, setSelectedVideo] = useState(null)
  const [activeSource, setActiveSource] = useState('0')
  const [status, setStatus] = useState({
    state: SAFE,
    confidence: 0,
    label: '',
    message: SAFE,
    updated_at: null,
  })
  const [events, setEvents] = useState([])
  const [socketConnected, setSocketConnected] = useState(false)
  const [busy, setBusy] = useState(false)
  const [uploadBusy, setUploadBusy] = useState(false)
  const [toast, setToast] = useState('')
  const [streamNonce, setStreamNonce] = useState(0)
  const [streamError, setStreamError] = useState('')

  const reconnectRef = useRef(null)
  const previousStateRef = useRef(SAFE)
  const streamRetryRef = useRef(null)

  const streamUrl = `${API_ROOT}/api/stream/?v=${streamNonce}`

  const statusClass =
    status.state === FIRE ? 'state-fire' : status.state === SMOKE ? 'state-smoke' : 'state-safe'

  const refreshEvents = async () => {
    try {
      const response = await fetch(`${API_ROOT}/api/events/?limit=120`)
      if (!response.ok) {
        return
      }

      const data = await response.json()
      if (Array.isArray(data.items)) {
        setEvents(data.items)
      }
    } catch {
      // Ignore transient polling errors while websocket reconnects.
    }
  }

  const refreshStatus = async () => {
    try {
      const response = await fetch(`${API_ROOT}/api/status/`)
      if (!response.ok) {
        return
      }

      const data = await response.json()
      setStatus((prev) => ({ ...prev, ...data }))
      if (data.source) {
        setActiveSource(String(data.source))
        setSourceInput(String(data.source))
      }
    } catch {
      // Keep previous status when API is temporarily unavailable.
    }
  }

  useEffect(() => {
    const timer = window.setTimeout(() => {
      refreshStatus()
      refreshEvents()
    }, 0)

    return () => window.clearTimeout(timer)
  }, [])

  useEffect(() => {
    const wsUrl = inferWsUrl()
    let socket
    let isClosed = false

    const connect = () => {
      socket = new WebSocket(wsUrl)

      socket.onopen = () => {
        setSocketConnected(true)
      }

      socket.onclose = () => {
        setSocketConnected(false)
        if (!isClosed) {
          reconnectRef.current = window.setTimeout(connect, 1200)
        }
      }

      socket.onerror = () => {
        socket.close()
      }

      socket.onmessage = (event) => {
        let payload
        try {
          payload = JSON.parse(event.data)
        } catch {
          return
        }

        if (payload.type === 'snapshot') {
          if (payload.status) {
            setStatus(payload.status)
            if (payload.status.source) {
              setSourceInput(String(payload.status.source))
              setActiveSource(String(payload.status.source))
            }
          }
          if (Array.isArray(payload.events)) {
            setEvents(payload.events)
          }
          return
        }

        if (payload.type === 'status_update' && payload.status) {
          setStatus(payload.status)
          return
        }

        if (payload.type === 'event_log' && payload.event) {
          setEvents((prev) => [payload.event, ...prev].slice(0, 120))
          setToast(`Realtime alert: ${payload.event.status}`)
          return
        }

        if (payload.type === 'source_ack' && payload.status) {
          setStatus(payload.status)
          if (payload.status.source) {
            setActiveSource(String(payload.status.source))
            setSourceInput(String(payload.status.source))
          }
          return
        }

        if (payload.type === 'source_error') {
          setToast(payload.error || 'Invalid source')
        }
      }
    }

    connect()

    return () => {
      isClosed = true
      if (reconnectRef.current) {
        window.clearTimeout(reconnectRef.current)
      }
      if (socket && socket.readyState <= 1) {
        socket.close()
      }
    }
  }, [])

  useEffect(() => {
    if (!toast) {
      return undefined
    }

    const timer = window.setTimeout(() => setToast(''), 2800)
    return () => window.clearTimeout(timer)
  }, [toast])

  useEffect(() => {
    if (status.state !== SAFE && previousStateRef.current !== status.state) {
      setToast(`Realtime alert: ${status.state}`)
    }
    previousStateRef.current = status.state
  }, [status.state])

  useEffect(() => {
    return () => {
      if (streamRetryRef.current) {
        window.clearTimeout(streamRetryRef.current)
      }
    }
  }, [])

  const scheduleStreamReconnect = (message) => {
    setStreamError(message || 'Stream disconnected, reconnecting...')
    if (streamRetryRef.current) {
      return
    }

    streamRetryRef.current = window.setTimeout(() => {
      streamRetryRef.current = null
      setStreamNonce((prev) => prev + 1)
    }, 900)
  }

  const setSourceByApi = async (nextSource, successMessage) => {
    if (!nextSource) {
      throw new Error('Source is required')
    }

    const response = await fetch(`${API_ROOT}/api/source/`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ source: nextSource }),
    })

    const body = await response.json().catch(() => ({}))
    if (!response.ok) {
      throw new Error(body.error || 'Failed to switch source')
    }

    if (body.status) {
      setStatus(body.status)
      if (body.status.source) {
        setActiveSource(String(body.status.source))
      }
    } else {
      setActiveSource(nextSource)
    }

    if (successMessage) {
      setToast(successMessage)
    }
    setStreamError('')
    setStreamNonce((prev) => prev + 1)
    refreshEvents()
    return body
  }

  const applySource = async (event) => {
    event.preventDefault()
    const nextSource = sourceInput.trim()
    if (!nextSource) {
      return
    }

    setBusy(true)
    try {
      await setSourceByApi(nextSource, `Camera source switched to: ${nextSource}`)
    } catch (error) {
      setToast(error.message)
    } finally {
      setBusy(false)
    }
  }

  const applyVideoLink = async (event) => {
    event.preventDefault()
    const nextLink = videoLinkInput.trim()
    if (!nextLink) {
      setToast('Please paste a video link first')
      return
    }

    setBusy(true)
    try {
      await setSourceByApi(nextLink, 'Video link loaded for detection')
      setSourceInput(nextLink)
    } catch (error) {
      setToast(error.message)
    } finally {
      setBusy(false)
    }
  }

  const applyUploadVideo = async (event) => {
    event.preventDefault()
    if (!selectedVideo) {
      setToast('Please choose a video file to upload')
      return
    }

    setUploadBusy(true)
    try {
      const formData = new FormData()
      formData.append('video', selectedVideo)

      const response = await fetch(`${API_ROOT}/api/upload-video/`, {
        method: 'POST',
        body: formData,
      })

      const body = await response.json().catch(() => ({}))
      if (!response.ok) {
        throw new Error(body.error || 'Failed to upload video')
      }

      if (body.status) {
        setStatus(body.status)
        if (body.status.source) {
          setActiveSource(String(body.status.source))
          setSourceInput(String(body.status.source))
        }
      }

      setToast(`Uploaded video loaded: ${body.filename || selectedVideo.name}`)
      setStreamError('')
      setStreamNonce((prev) => prev + 1)
      setSelectedVideo(null)
      const fileInput = document.getElementById('video-upload-input')
      if (fileInput) {
        fileInput.value = ''
      }
      refreshEvents()
    } catch (error) {
      setToast(error.message)
    } finally {
      setUploadBusy(false)
    }
  }

  return (
    <div className="dashboard-root">
      <div className="noise-layer" aria-hidden="true" />

      <header className="dashboard-header panel card-in">
        <div>
          <p className="eyebrow">Fire & Smoke Security Dashboard</p>
          <h1>Realtime Camera Monitor</h1>
        </div>
        <div className="connection-wrap">
          <span className={`dot ${socketConnected ? 'dot-on' : 'dot-off'}`} />
          <span>{socketConnected ? 'Realtime Connected' : 'Reconnecting WebSocket...'}</span>
        </div>
      </header>

      {status.state !== SAFE && (
        <div className={`alert-strip ${statusClass}`}>
          <strong>{status.state}</strong>
          <span>Action required immediately.</span>
        </div>
      )}

      {toast && <div className="toast">{toast}</div>}

      <main className="dashboard-grid">
        <section className="panel stream-panel card-in stagger-1">
          <div className="panel-head">
            <div>
              <h2>Live Feed</h2>
              <p>Bounding boxes are drawn by YOLOv11 on backend stream.</p>
            </div>
            <span className={`status-pill ${statusClass}`}>{status.state}</span>
          </div>

          <div className="stream-shell">
            <MJPEGStream
              streamUrl={streamUrl}
              onError={(msg) => scheduleStreamReconnect(msg)}
              onRetry={() => scheduleStreamReconnect()}
            />
            {streamError && <div className="stream-error">{streamError}</div>}
            <div className="scanline" aria-hidden="true" />
          </div>

          <form className="source-form" onSubmit={applySource}>
            <label htmlFor="source-input">Camera Source (webcam or local path)</label>
            <div className="source-controls">
              <input
                id="source-input"
                value={sourceInput}
                onChange={(event) => setSourceInput(event.target.value)}
                placeholder="0 hoặc rtsp://..."
                autoComplete="off"
              />
              <button disabled={busy} type="submit">
                {busy ? 'Switching...' : 'Apply'}
              </button>
            </div>
            <p className="source-note">
              Dùng 0 cho webcam, hoặc đường dẫn file local như D:/videos/fire.mp4
            </p>
          </form>

          <form className="source-form" onSubmit={applyVideoLink}>
            <label htmlFor="video-link-input">Video Link</label>
            <div className="source-controls">
              <input
                id="video-link-input"
                value={videoLinkInput}
                onChange={(event) => setVideoLinkInput(event.target.value)}
                placeholder="https://example.com/fire.mp4 hoặc rtsp://..."
                autoComplete="off"
              />
              <button disabled={busy} type="submit">
                {busy ? 'Loading...' : 'Load Link'}
              </button>
            </div>
            <p className="source-note">Hỗ trợ direct video URL hoặc RTSP stream URL.</p>
          </form>

          <form className="source-form" onSubmit={applyUploadVideo}>
            <label htmlFor="video-upload-input">Upload Video</label>
            <div className="upload-controls">
              <input
                id="video-upload-input"
                type="file"
                accept="video/*"
                onChange={(event) => setSelectedVideo(event.target.files?.[0] ?? null)}
              />
              <button disabled={uploadBusy} type="submit">
                {uploadBusy ? 'Uploading...' : 'Upload & Detect'}
              </button>
            </div>
            <p className="source-note">
              {selectedVideo ? `Selected: ${selectedVideo.name}` : 'Chọn file video để backend detect trực tiếp.'}
            </p>
          </form>
        </section>

        <section className="right-column">
          <article className={`panel status-card card-in stagger-2 ${statusClass}`}>
            <h2>System State</h2>
            <p className="state-value">{status.state}</p>
            <dl>
              <div>
                <dt>Label</dt>
                <dd>{status.label || '--'}</dd>
              </div>
              <div>
                <dt>Confidence</dt>
                <dd>{Number(status.confidence || 0).toFixed(3)}</dd>
              </div>
              <div>
                <dt>Updated</dt>
                <dd>{formatTimestamp(status.updated_at)}</dd>
              </div>
              <div>
                <dt>Source</dt>
                <dd>{status.source || activeSource}</dd>
              </div>
              <div>
                <dt>Message</dt>
                <dd>{status.message || '--'}</dd>
              </div>
            </dl>
          </article>

          <article className="panel log-panel card-in stagger-3">
            <div className="panel-head">
              <h2>Fire Event Log</h2>
              <button className="ghost-btn" onClick={refreshEvents} type="button">
                Refresh
              </button>
            </div>

            <ul className="event-list">
              {events.length === 0 && <li className="empty">No smoke/fire events recorded yet.</li>}

              {events.map((eventItem) => {
                const eventClass =
                  eventItem.status === FIRE
                    ? 'event-fire'
                    : eventItem.status === SMOKE
                      ? 'event-smoke'
                      : 'event-safe'

                return (
                  <li key={eventItem.id} className={`event-item ${eventClass}`}>
                    <div>
                      <strong>{eventItem.status}</strong>
                      <p>
                        label: {eventItem.label || '--'} • conf: {Number(eventItem.confidence || 0).toFixed(3)}
                      </p>
                    </div>
                    <span>{formatTimestamp(eventItem.created_at)}</span>
                  </li>
                )
              })}
            </ul>
          </article>
        </section>
      </main>
    </div>
  )
}

export default App
