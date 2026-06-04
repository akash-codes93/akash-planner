import { useState, useRef, useEffect, useCallback } from 'react'
import { supabase } from '../lib/supabase'
import Toast from './Toast'

const EMPTY_FORM = {
  title: '',
  category: 'work',
  item_type: 'task',
  priority: 50,
  effort_minutes: '',
  cognitive_load: 'medium',
  due_date: '',
  url: '',
  tags: '',
  notes: '',
}

const CATEGORIES = [
  { id: 'work',          label: 'Work',      icon: '💼' },
  { id: 'interview_prep', label: 'Interview', icon: '🎯' },
  { id: 'learning',      label: 'Learning',  icon: '📚' },
  { id: 'personal',      label: 'Personal',  icon: '🌿' },
  { id: 'hobby',         label: 'Hobby',     icon: '🎮' },
]

const ITEM_TYPES = [
  { id: 'task',        label: 'Task' },
  { id: 'article',     label: 'Article' },
  { id: 'video',       label: 'Video' },
  { id: 'course',      label: 'Course' },
  { id: 'dsa_problem', label: 'DSA' },
  { id: 'note',        label: 'Note' },
]

const COGNITIVE_LOADS = [
  { id: 'low',    label: '🟢 Low' },
  { id: 'medium', label: '🟡 Medium' },
  { id: 'high',   label: '🔴 High' },
]

function priorityColor(val) {
  if (val >= 80) return 'var(--red)'
  if (val >= 50) return 'var(--amber)'
  return 'var(--green)'
}

export default function Capture() {
  const [form, setForm] = useState(EMPTY_FORM)
  const [showMore, setShowMore] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [toast, setToast] = useState(null)

  const titleRef = useRef(null)

  useEffect(() => {
    titleRef.current?.focus()
  }, [])

  const set = useCallback((key, value) => {
    setForm((prev) => ({ ...prev, [key]: value }))
  }, [])

  const handleChange = useCallback((e) => {
    const { name, value } = e.target
    set(name, value)
  }, [set])

  const addEffort = useCallback((minutes) => {
    setForm((prev) => ({
      ...prev,
      effort_minutes: String(Math.max(0, Number(prev.effort_minutes || 0) + minutes)),
    }))
  }, [])

  const handleSubmit = useCallback(
    async (e) => {
      e.preventDefault()
      if (!form.title.trim()) return

      setSubmitting(true)

      const tags = form.tags
        ? form.tags.split(',').map((t) => t.trim()).filter(Boolean)
        : []

      const payload = {
        title: form.title.trim(),
        category: form.category,
        item_type: form.item_type || 'task',
        priority: Number(form.priority),
        effort_minutes: form.effort_minutes ? Number(form.effort_minutes) : null,
        cognitive_load: form.cognitive_load || null,
        due_date: form.due_date || null,
        url: form.url.trim() || null,
        tags,
        notes: form.notes.trim() || null,
        status: 'backlog',
        source: 'quick_capture',
      }

      const { error } = await supabase.from('items').insert(payload)

      if (error) {
        setToast({ message: `Failed to add item: ${error.message}`, type: 'error' })
      } else {
        // Clear form but keep category
        const savedCategory = form.category
        setForm({ ...EMPTY_FORM, category: savedCategory })
        setShowMore(false)
        setToast({ message: 'Item added to backlog!', type: 'success' })
        titleRef.current?.focus()
      }

      setSubmitting(false)
    },
    [form],
  )

  return (
    <div className="capture">
      <div className="capture__scroll">
        <div className="capture__card">
          <form onSubmit={handleSubmit}>
            {/* Big title input */}
            <input
              ref={titleRef}
              name="title"
              className="capture__title-input"
              type="text"
              value={form.title}
              onChange={handleChange}
              placeholder="What do you want to capture?"
              required
              autoComplete="off"
            />

            {/* Category pill grid */}
            <div className="capture__section-label">Category</div>
            <div className="capture__pill-grid">
              {CATEGORIES.map((cat) => (
                <button
                  key={cat.id}
                  type="button"
                  className={`capture__pill ${form.category === cat.id ? 'capture__pill--active' : ''}`}
                  onClick={() => set('category', cat.id)}
                >
                  {cat.icon} {cat.label}
                </button>
              ))}
            </div>

            {/* More details toggle */}
            <button
              type="button"
              className="capture__more-toggle"
              onClick={() => setShowMore((v) => !v)}
            >
              {showMore ? '－ Less details' : '＋ More details'}
            </button>

            {/* More details section */}
            <div className={`capture__extra ${showMore ? 'capture__extra--open' : ''}`}>
              <div className="capture__extra-inner">
                {/* Item type */}
                <div className="capture__field">
                  <div className="capture__section-label">Type</div>
                  <div className="capture__pill-grid">
                    {ITEM_TYPES.map((t) => (
                      <button
                        key={t.id}
                        type="button"
                        className={`capture__pill ${form.item_type === t.id ? 'capture__pill--active' : ''}`}
                        onClick={() => set('item_type', t.id)}
                      >
                        {t.label}
                      </button>
                    ))}
                  </div>
                </div>

                {/* Priority slider */}
                <div className="capture__field">
                  <div className="capture__section-label">
                    Priority —{' '}
                    <span style={{ color: priorityColor(form.priority), fontWeight: 700 }}>
                      {form.priority}
                    </span>
                  </div>
                  <input
                    name="priority"
                    type="range"
                    className="capture__range"
                    min="0"
                    max="100"
                    value={form.priority}
                    onChange={handleChange}
                    style={{
                      '--thumb-color': priorityColor(form.priority),
                    }}
                  />
                </div>

                {/* Effort */}
                <div className="capture__field">
                  <div className="capture__section-label">Effort (minutes)</div>
                  <div className="capture__effort-row">
                    <input
                      name="effort_minutes"
                      type="number"
                      className="capture__input"
                      value={form.effort_minutes}
                      onChange={handleChange}
                      placeholder="0"
                      min="1"
                    />
                    <div className="capture__effort-chips">
                      {[15, 30, 60].map((m) => (
                        <button
                          key={m}
                          type="button"
                          className="capture__effort-chip"
                          onClick={() => addEffort(m)}
                        >
                          +{m}m
                        </button>
                      ))}
                    </div>
                  </div>
                </div>

                {/* Cognitive load */}
                <div className="capture__field">
                  <div className="capture__section-label">Cognitive Load</div>
                  <div className="capture__toggle-group">
                    {COGNITIVE_LOADS.map((l) => (
                      <button
                        key={l.id}
                        type="button"
                        className={`capture__toggle-btn ${form.cognitive_load === l.id ? 'capture__toggle-btn--active' : ''}`}
                        onClick={() => set('cognitive_load', l.id)}
                      >
                        {l.label}
                      </button>
                    ))}
                  </div>
                </div>

                {/* Due date */}
                <div className="capture__field">
                  <label className="capture__section-label" htmlFor="cap-due">Due Date</label>
                  <input
                    id="cap-due"
                    name="due_date"
                    type="date"
                    className="capture__input"
                    value={form.due_date}
                    onChange={handleChange}
                  />
                </div>

                {/* URL */}
                <div className="capture__field">
                  <label className="capture__section-label" htmlFor="cap-url">URL</label>
                  <input
                    id="cap-url"
                    name="url"
                    type="url"
                    className="capture__input capture__input--mono"
                    value={form.url}
                    onChange={handleChange}
                    placeholder="https://…"
                  />
                </div>

                {/* Tags */}
                <div className="capture__field">
                  <label className="capture__section-label" htmlFor="cap-tags">Tags (comma-separated)</label>
                  <input
                    id="cap-tags"
                    name="tags"
                    type="text"
                    className="capture__input"
                    value={form.tags}
                    onChange={handleChange}
                    placeholder="react, frontend, urgent"
                  />
                </div>

                {/* Notes */}
                <div className="capture__field">
                  <label className="capture__section-label" htmlFor="cap-notes">Notes</label>
                  <textarea
                    id="cap-notes"
                    name="notes"
                    className="capture__textarea"
                    value={form.notes}
                    onChange={handleChange}
                    placeholder="Any extra context…"
                    rows={3}
                  />
                </div>
              </div>
            </div>

            {/* Submit */}
            <button
              type="submit"
              className="capture__submit-btn"
              disabled={submitting || !form.title.trim()}
            >
              {submitting ? (
                <>
                  <span className="capture__spinner" /> Adding…
                </>
              ) : (
                'Add to Backlog'
              )}
            </button>
          </form>
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
