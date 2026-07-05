import { useState } from 'react'

const API_BASE = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000'

const QUICK_QUESTIONS = [
  'What should I work on next?',
  'What are my open items?',
  'What should I prioritize?',
  'Catch me up',
]

export default function AiPlanner() {
  const [expanded, setExpanded] = useState(false)
  const [question, setQuestion] = useState('')
  const [messages, setMessages] = useState([])
  const [loading, setLoading] = useState(false)

  async function ask(q) {
    if (!q.trim()) return
    const userMsg = { role: 'user', text: q }
    setMessages((prev) => [...prev, userMsg])
    setQuestion('')
    setLoading(true)
    try {
      const res = await fetch(`${API_BASE}/api/ai/ask`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: q }),
      })
      if (!res.ok) {
        setMessages((prev) => [...prev, { role: 'assistant', text: `Server error (${res.status}). Make sure the backend is running.` }])
        return
      }
      const data = await res.json()
      setMessages((prev) => [...prev, { role: 'assistant', text: data.answer || '' }])
    } catch {
      setMessages((prev) => [...prev, { role: 'assistant', text: 'Backend not reachable. Make sure the server is running.' }])
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className={`ai-planner ${expanded ? 'ai-planner-expanded' : ''}`}>
      <button className="ai-planner-toggle" onClick={() => setExpanded(!expanded)} type="button" aria-label="Toggle AI planner">
        <svg className="ai-planner-sparkle" viewBox="0 0 24 24" width="18" height="18" fill="none" xmlns="http://www.w3.org/2000/svg">
          <path d="M12 2l1.5 6.5L20 10l-6.5 1.5L12 18l-1.5-6.5L4 10l6.5-1.5L12 2z" fill="currentColor" />
          <path d="M18 14l.8 3.2L22 18l-3.2.8L18 22l-.8-3.2L14 18l3.2-.8L18 14z" fill="currentColor" opacity="0.6" />
        </svg>
        {!expanded && <span className="ai-planner-badge">AI</span>}
      </button>

      {expanded && (
        <div className="ai-planner-card">
          <div className="ai-planner-header">
            <svg className="ai-planner-sparkle" viewBox="0 0 24 24" width="16" height="16" fill="none" xmlns="http://www.w3.org/2000/svg">
              <path d="M12 2l1.5 6.5L20 10l-6.5 1.5L12 18l-1.5-6.5L4 10l6.5-1.5L12 2z" fill="currentColor" />
              <path d="M18 14l.8 3.2L22 18l-3.2.8L18 22l-.8-3.2L14 18l3.2-.8L18 14z" fill="currentColor" opacity="0.6" />
            </svg>
            <span className="ai-planner-title">AI Planner</span>
          </div>

          <div className="ai-planner-messages">
            {messages.length === 0 && (
              <div className="ai-planner-welcome">
                <p>Ask me about your tasks and I'll help you plan.</p>
                <div className="ai-planner-quick-chips">
                  {QUICK_QUESTIONS.map((q) => (
                    <button key={q} className="ai-planner-chip" onClick={() => ask(q)} type="button">
                      {q}
                    </button>
                  ))}
                </div>
              </div>
            )}
            {messages.map((msg, i) => (
              <div key={i} className={`ai-planner-msg ai-planner-msg-${msg.role}`}>
                {(msg.text || '').split('\n').map((line, j) => (
                  <p key={j}>{line || '\u00A0'}</p>
                ))}
              </div>
            ))}
            {loading && <div className="ai-planner-msg ai-planner-msg-assistant ai-planner-thinking">Thinking...</div>}
          </div>

          <form className="ai-planner-input-row" onSubmit={(e) => { e.preventDefault(); ask(question) }}>
            <input
              className="ai-planner-input"
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="Ask about your tasks..."
              disabled={loading}
            />
          </form>
        </div>
      )}
    </div>
  )
}