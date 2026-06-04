import { useState, useRef, useEffect, useCallback } from 'react'
import Toast from './Toast'

const API_URL = import.meta.env.VITE_API_URL

function generateUUID() {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0
    const v = c === 'x' ? r : (r & 0x3) | 0x8
    return v.toString(16)
  })
}

function getOrCreateThreadId() {
  let id = localStorage.getItem('akash-thread-id')
  if (!id) {
    id = generateUUID()
    localStorage.setItem('akash-thread-id', id)
  }
  return id
}

const STEP_LABELS = {
  thought: '🧠 Thought',
  action: '⚡ Action',
  observation: '👁 Observation',
  answer: '✅ Answer',
}

function Step({ step }) {
  const label = step.type === 'action' && step.tool_name
    ? `⚡ Action: ${step.tool_name}`
    : STEP_LABELS[step.type] || step.type

  return (
    <div className={`step step--${step.type}`}>
      <div className="step__label">{label}</div>
      <div className="step__content">{step.content}</div>
      {step.type === 'action' && step.tool_input && (
        <pre className="step__code">
          {JSON.stringify(step.tool_input, null, 2)}
        </pre>
      )}
    </div>
  )
}

function Message({ msg }) {
  if (msg.role === 'user') {
    return (
      <div className="chat__message chat__message--user">
        <div className="chat__bubble chat__bubble--user">{msg.content}</div>
      </div>
    )
  }

  return (
    <div className="chat__message chat__message--agent">
      {msg.visibleSteps && msg.visibleSteps.length > 0 && (
        <div className="chat__steps">
          {msg.visibleSteps.map((step, i) => (
            <Step key={i} step={step} />
          ))}
        </div>
      )}
    </div>
  )
}

export default function Chat() {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [threadId, setThreadId] = useState(getOrCreateThreadId)
  const [error, setError] = useState(null)
  const [toast, setToast] = useState(null)

  const messagesEndRef = useRef(null)
  const textareaRef = useRef(null)

  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [])

  useEffect(() => {
    scrollToBottom()
  }, [messages, scrollToBottom])

  const animateSteps = useCallback((steps, msgIndex) => {
    steps.forEach((step, i) => {
      setTimeout(() => {
        setMessages((prev) => {
          const updated = [...prev]
          const target = updated[msgIndex]
          if (!target) return prev
          updated[msgIndex] = {
            ...target,
            visibleSteps: [...(target.visibleSteps || []), step],
          }
          return updated
        })
      }, i * 150)
    })
  }, [])

  const sendMessage = useCallback(async () => {
    const text = input.trim()
    if (!text || loading) return

    setInput('')
    setError(null)

    const userMsg = { role: 'user', content: text }
    setMessages((prev) => [...prev, userMsg])

    setLoading(true)

    // Placeholder for agent message — steps fill in progressively
    const agentMsgIndex = messages.length + 1
    setMessages((prev) => [
      ...prev,
      { role: 'agent', content: '', visibleSteps: [], allSteps: [] },
    ])

    try {
      const res = await fetch(`${API_URL}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text, thread_id: threadId }),
      })

      if (!res.ok) {
        const detail = await res.text()
        throw new Error(`Server error ${res.status}: ${detail}`)
      }

      const data = await res.json()
      const allSteps = [...(data.steps || [])]

      // Update with all steps stored, then animate visible ones
      setMessages((prev) => {
        const updated = [...prev]
        updated[agentMsgIndex] = {
          role: 'agent',
          content: data.answer || '',
          visibleSteps: [],
          allSteps,
        }
        return updated
      })

      animateSteps(allSteps, agentMsgIndex)
    } catch (err) {
      setError(err.message || 'Failed to reach the agent. Is the backend running?')
      // Remove the empty placeholder
      setMessages((prev) => prev.slice(0, -1))
    } finally {
      setLoading(false)
    }
  }, [input, loading, messages.length, threadId, animateSteps])

  const handleKeyDown = useCallback(
    (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault()
        sendMessage()
      }
    },
    [sendMessage],
  )

  const handleNewConversation = useCallback(() => {
    const newId = generateUUID()
    localStorage.setItem('akash-thread-id', newId)
    setThreadId(newId)
    setMessages([])
    setError(null)
    setToast({ message: 'New conversation started', type: 'success' })
    textareaRef.current?.focus()
  }, [])

  // Auto-resize textarea
  const handleInput = useCallback((e) => {
    setInput(e.target.value)
    e.target.style.height = 'auto'
    e.target.style.height = Math.min(e.target.scrollHeight, 160) + 'px'
  }, [])

  return (
    <div className="chat">
      <div className="chat__header">
        <span className="chat__header-title">
          thread / {threadId.slice(0, 8)}…
        </span>
        <button className="chat__new-btn" onClick={handleNewConversation}>
          + new conversation
        </button>
      </div>

      <div className="chat__messages">
        {messages.length === 0 && !loading && (
          <div className="chat__empty">
            <span className="chat__empty-icon">⚡</span>
            <div className="chat__empty-title">What should I work on?</div>
            <div className="chat__empty-hint">
              Ask the agent to plan your day, add tasks, or suggest what to
              do next based on your energy level.
            </div>
          </div>
        )}

        {messages.map((msg, i) => (
          <Message key={i} msg={msg} />
        ))}

        {loading && (
          <div className="chat__message chat__message--agent">
            <div className="chat__loading">
              <div className="chat__loading-dots">
                <span className="chat__loading-dot" />
                <span className="chat__loading-dot" />
                <span className="chat__loading-dot" />
              </div>
              reasoning…
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {error && (
        <div className="chat__error" role="alert">
          {error}
        </div>
      )}

      <div className="chat__input-area">
        <div className="chat__input-row">
          <textarea
            ref={textareaRef}
            className="chat__textarea"
            value={input}
            onChange={handleInput}
            onKeyDown={handleKeyDown}
            placeholder="Ask anything… (Enter to send, Shift+Enter for newline)"
            rows={1}
            disabled={loading}
          />
          <button
            className="chat__send-btn"
            onClick={sendMessage}
            disabled={loading || !input.trim()}
            aria-label="Send"
          >
            ↑
          </button>
        </div>
      </div>

      {toast && (
        <Toast
          message={toast.message}
          type={toast.type}
          onDismiss={() => setToast(null)}
        />
      )}
    </div>
  )
}
