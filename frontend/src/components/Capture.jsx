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

export default function Capture() {
  const [form, setForm] = useState(EMPTY_FORM)
  const [showMore, setShowMore] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [toast, setToast] = useState(null)

  const titleRef = useRef(null)

  useEffect(() => {
    titleRef.current?.focus()
  }, [])

  const handleChange = useCallback((e) => {
    const { name, value } = e.target
    setForm((prev) => ({ ...prev, [name]: value }))
  }, [])

  const handleSubmit = useCallback(
    async (e) => {
      e.preventDefault()
      if (!form.title.trim()) return

      setSubmitting(true)

      const tags = form.tags
        ? form.tags
            .split(',')
            .map((t) => t.trim())
            .filter(Boolean)
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
        setForm(EMPTY_FORM)
        setShowMore(false)
        setToast({ message: 'Item added!', type: 'success' })
        titleRef.current?.focus()
      }

      setSubmitting(false)
    },
    [form],
  )

  return (
    <div className="capture">
      <div className="capture__header">
        <span className="capture__title">quick capture</span>
      </div>

      <div className="capture__content">
        <form className="capture__form" onSubmit={handleSubmit}>
          {/* Required fields */}
          <div className="form-group">
            <label className="form-label" htmlFor="capture-title">
              Title *
            </label>
            <input
              ref={titleRef}
              id="capture-title"
              name="title"
              className="form-input"
              type="text"
              value={form.title}
              onChange={handleChange}
              placeholder="What do you need to do or remember?"
              required
            />
          </div>

          <div className="form-group">
            <label className="form-label" htmlFor="capture-category">
              Category *
            </label>
            <select
              id="capture-category"
              name="category"
              className="form-select"
              value={form.category}
              onChange={handleChange}
            >
              <option value="work">Work</option>
              <option value="interview_prep">Interview Prep</option>
              <option value="learning">Learning</option>
              <option value="personal">Personal</option>
              <option value="hobby">Hobby</option>
            </select>
          </div>

          {/* Toggle more details */}
          <button
            type="button"
            className="capture__more-toggle"
            onClick={() => setShowMore((v) => !v)}
          >
            {showMore ? '▲ Hide details' : '▼ More details (optional)'}
          </button>

          {showMore && (
            <div className="capture__extra">
              <div className="form-group">
                <label className="form-label" htmlFor="capture-item-type">
                  Type
                </label>
                <select
                  id="capture-item-type"
                  name="item_type"
                  className="form-select"
                  value={form.item_type}
                  onChange={handleChange}
                >
                  <option value="task">Task</option>
                  <option value="article">Article</option>
                  <option value="video">Video</option>
                  <option value="course">Course</option>
                  <option value="dsa_problem">DSA Problem</option>
                  <option value="note">Note</option>
                  <option value="idea">Idea</option>
                </select>
              </div>

              <div className="form-group">
                <label className="form-label" htmlFor="capture-priority">
                  Priority: {form.priority}
                </label>
                <div className="form-range-row">
                  <input
                    id="capture-priority"
                    name="priority"
                    type="range"
                    className="form-range"
                    min="0"
                    max="100"
                    value={form.priority}
                    onChange={handleChange}
                  />
                  <span className="form-range-value">{form.priority}</span>
                </div>
              </div>

              <div className="form-group">
                <label className="form-label" htmlFor="capture-effort">
                  Effort (minutes)
                </label>
                <input
                  id="capture-effort"
                  name="effort_minutes"
                  type="number"
                  className="form-input"
                  value={form.effort_minutes}
                  onChange={handleChange}
                  placeholder="e.g. 30"
                  min="1"
                />
              </div>

              <div className="form-group">
                <span className="form-label">Cognitive Load</span>
                <div className="form-radio-group">
                  {['low', 'medium', 'high'].map((level) => (
                    <label key={level} className="form-radio-label">
                      <input
                        type="radio"
                        name="cognitive_load"
                        value={level}
                        checked={form.cognitive_load === level}
                        onChange={handleChange}
                      />
                      {level === 'low' ? '🟢' : level === 'medium' ? '🟡' : '🔴'}
                      {' '}{level}
                    </label>
                  ))}
                </div>
              </div>

              <div className="form-group">
                <label className="form-label" htmlFor="capture-due">
                  Due Date
                </label>
                <input
                  id="capture-due"
                  name="due_date"
                  type="date"
                  className="form-input"
                  value={form.due_date}
                  onChange={handleChange}
                />
              </div>

              <div className="form-group">
                <label className="form-label" htmlFor="capture-url">
                  URL
                </label>
                <input
                  id="capture-url"
                  name="url"
                  type="url"
                  className="form-input"
                  value={form.url}
                  onChange={handleChange}
                  placeholder="https://…"
                />
              </div>

              <div className="form-group">
                <label className="form-label" htmlFor="capture-tags">
                  Tags (comma-separated)
                </label>
                <input
                  id="capture-tags"
                  name="tags"
                  type="text"
                  className="form-input"
                  value={form.tags}
                  onChange={handleChange}
                  placeholder="e.g. react, frontend, urgent"
                />
              </div>

              <div className="form-group">
                <label className="form-label" htmlFor="capture-notes">
                  Notes
                </label>
                <textarea
                  id="capture-notes"
                  name="notes"
                  className="form-textarea"
                  value={form.notes}
                  onChange={handleChange}
                  placeholder="Any extra context…"
                  rows={3}
                />
              </div>
            </div>
          )}

          <button
            type="submit"
            className="capture__submit-btn"
            disabled={submitting || !form.title.trim()}
          >
            {submitting ? 'Adding…' : '+ Add Item'}
          </button>
        </form>
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
