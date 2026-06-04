import { useEffect } from 'react'

export default function Toast({ message, type = 'success', onDismiss }) {
  useEffect(() => {
    const timer = setTimeout(() => {
      onDismiss()
    }, 2500)
    return () => clearTimeout(timer)
  }, [onDismiss])

  return (
    <div className={`toast toast--${type}`} role="alert">
      {type === 'success' ? '✓ ' : '✕ '}
      {message}
    </div>
  )
}
