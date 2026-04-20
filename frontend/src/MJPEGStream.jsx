import { useEffect, useState } from 'react'

export default function MJPEGStream({ streamUrl, onError, onRetry }) {
  const [src, setSrc] = useState(streamUrl)

  useEffect(() => {
    setSrc(streamUrl)
  }, [streamUrl])

  const handleError = () => {
    onError?.('Cannot load MJPEG stream')
    onRetry?.()
  }

  const handleLoad = () => {
    onError?.('')
  }

  return (
    <img
      src={src}
      className="stream-image"
      alt="Realtime detection stream"
      onError={handleError}
      onLoad={handleLoad}
    />
  )
}
