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

// Inline markdown renderer — no external deps
function renderMarkdown(text) {
  if (!text) return []

  const lines = text.split('\n')
  const elements = []
  let listItems = []
  let orderedItems = []
  let key = 0

  function flushList() {
    if (listItems.length > 0) {
      elements.push(
        <ul key={key++} className="chat__md-list">
          {listItems.map((item, i) => (
            <li key={i}>{renderInline(item)}</li>
          ))}
        </ul>
      )
      listItems = []
    }
    if (orderedItems.length > 0) {
      elements.push(
        <ol key={key++} className="chat__md-list chat__md-list--ordered">
          {orderedItems.map((item, i) => (
            <li key={i}>{renderInline(item)}</li>
          ))}
        </ol>
      )
      orderedItems = []
    }
  }

  function renderInline(str) {
    // Split on bold (**text**) and code (`code`)
    const parts = str.split(/(\*\*[^*]+\*\*|`[^`]+`)/g)
    return parts.map((part, i) => {
      if (part.startsWith('**') && part.endsWith('**')) {
        return <strong key={i}>{part.slice(2, -2)}</strong>
      }
      if (part.startsWith('`') && part.endsWith('`')) {
        return <code key={i} className="chat__md-code">{part.slice(1, -1)}</code>
      }
      return part
    })
  }

  for (const line of lines) {
    // Unordered list
    const ulMatch = line.match(/^[-•*]\s+(.+)/)
    if (ulMatch) {
      flushList()
      listItems.push(ulMatch[1])
      continue
    }
    // Ordered list
    const olMatch = line.match(/^\d+\.\s+(.+)/)
    if (olMatch) {
      flushList()
      orderedItems.push(olMatch[1])
      continue
    }

    flushList()

    if (line.trim() === '') {
      elements.push(<br key={key++} />)
    } else {
      elements.push(
        <p key={key++} className="chat__md-p">
          {renderInline(line)}
        </p>
      )
    }
  }

  flushList()
  return elements
}

function MessageBubble({ msg }) {
  const time = msg.timestamp
    ? new Date(msg.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    : null

  if (msg.role === 'user') {
    return (
      <div className="chat__message chat__message--user">
        <div className="chat__bubble chat__bubble--user">{msg.content}</div>
        {time && <span className="chat__timestamp">{time}</span>}
      </div>
    )
  }

  return (
    <div className="chat__message chat__message--agent">
      <div className="chat__bubble chat__bubble--agent">
        {renderMarkdown(msg.content)}
      </div>
      {time && <span className="chat__timestamp">{time}</span>}
    </div>
  )
}

function LoadingBubble() {
  return (
    <div className="chat__message chat__message--agent">
      <div className="chat__bubble chat__bubble--agent chat__bubble--loading">
        <span className="chat__dot" />
        <span className="chat__dot" />
        <span className="chat__dot" />
      </div>
    </div>
  )
}

const QUICK_ACTIONS = [
  'What should I do now?',
  'Plan my morning',
  'Add a task',
]

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
  }, [messages, loading, scrollToBottom])

  const sendMessage = useCallback(async (text) => {
    const msgText = (text || input).trim()
    if (!msgText || loading) return

    setInput('')
    setError(null)

    // Reset textarea height
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto'
    }

    const userMsg = { id: generateUUID(), role: 'user', content: msgText, timestamp: new Date() }
    setMessages((prev) => [...prev, userMsg])
    setLoading(true)

    try {
      const res = await fetch(`${API_URL}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: msgText, thread_id: threadId }),
      })

      if (!res.ok) {
        const detail = await res.text()
        throw new Error(`Server error ${res.status}: ${detail}`)
      }

      const data = await res.json()
      const agentMsg = {
        id: generateUUID(),
        role: 'agent',
        content: data.answer || '',
        timestamp: new Date(),
      }
      setMessages((prev) => [...prev, agentMsg])
    } catch (err) {
      setError(err.message || 'Failed to reach the agent. Is the backend running?')
    } finally {
      setLoading(false)
    }
  }, [input, loading, threadId])

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

  const handleInput = useCallback((e) => {
    setInput(e.target.value)
    e.target.style.height = 'auto'
    e.target.style.height = Math.min(e.target.scrollHeight, 120) + 'px'
  }, [])

  const handleQuickAction = useCallback((text) => {
    sendMessage(text)
  }, [sendMessage])

  return (
    <div className="chat">
      {/* Header */}
      <div className="chat__header">
        <span className="chat__header-title">
          ⚡ <span className="chat__header-name">akash.planner</span>
        </span>
        <button className="chat__new-btn" onClick={handleNewConversation}>
          New chat
        </button>
      </div>

      {/* Messages */}
      <div className="chat__messages">
        {messages.length === 0 && !loading && (
          <div className="chat__empty">
            <span className="chat__empty-icon">⚡</span>
            <div className="chat__empty-greeting">Hey Akash</div>
            <div className="chat__empty-sub">What's on your mind?</div>
            <div className="chat__quick-actions">
              {QUICK_ACTIONS.map((action) => (
                <button
                  key={action}
                  className="chat__quick-chip"
                  onClick={() => handleQuickAction(action)}
                >
                  {action}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((msg) => (
          <MessageBubble key={msg.id} msg={msg} />
        ))}

        {loading && <LoadingBubble />}

        <div ref={messagesEndRef} />
      </div>

      {/* Error */}
      {error && (
        <div className="chat__error" role="alert">
          {error}
        </div>
      )}

      {/* Input area */}
      <div className="chat__input-area">
        <div className="chat__input-wrap">
          <textarea
            ref={textareaRef}
            className="chat__textarea"
            value={input}
            onChange={handleInput}
            onKeyDown={handleKeyDown}
            placeholder="Ask anything… (Enter to send)"
            rows={1}
            disabled={loading}
          />
          <button
            className="chat__send-btn"
            onClick={() => sendMessage()}
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
