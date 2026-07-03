import { useEffect, useMemo, useRef, useState } from 'react'
import './App.css'

const API_BASE = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000'

async function api(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  })
  if (!response.ok) {
    const body = await response.text()
    const error = new Error(body || `Request failed: ${response.status}`)
    error.status = response.status
    throw error
  }
  return response.status === 204 ? null : response.json()
}

function toDateInput(value) {
  if (!value) return ''
  return String(value).slice(0, 10)
}

function formatDayLabel(dateStr) {
  const date = new Date(`${dateStr}T00:00:00`)
  if (Number.isNaN(date.getTime())) return dateStr
  return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

function App() {
  const [tags, setTags] = useState([])
  const [tasks, setTasks] = useState([])
  const [activity, setActivity] = useState(null)
  const [activeTagId, setActiveTagId] = useState('')
  const [showDone, setShowDone] = useState(false)
  const [captureText, setCaptureText] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    loadTags()
    loadActivity()
  }, [])

  useEffect(() => {
    loadTasks()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTagId, showDone])

  async function loadTags() {
    try {
      const data = await api('/api/tags')
      setTags(data)
    } catch (err) {
      setError(err.message)
    }
  }

  async function loadActivity() {
    try {
      const data = await api('/api/activity?days=90')
      setActivity(data)
    } catch (err) {
      setError(err.message)
    }
  }

  async function loadTasks() {
    setLoading(true)
    setError('')
    try {
      const params = new URLSearchParams()
      params.set('with_subtasks', 'true')
      if (activeTagId) params.set('tag_id', activeTagId)
      if (!showDone) params.set('status', 'backlog')
      const data = await api(`/api/tasks?${params.toString()}`)
      setTasks(data)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  async function captureTask(event) {
    event.preventDefault()
    const title = captureText.trim()
    if (!title) return
    setCaptureText('')
    // Optimistic, non-blocking: fire the request and refresh once it resolves.
    api('/api/tasks', { method: 'POST', body: JSON.stringify({ title }) })
      .then(() => {
        loadTasks()
        loadActivity()
      })
      .catch((err) => setError(err.message))
  }

  async function toggleComplete(taskId) {
    try {
      await api(`/api/tasks/${taskId}/complete`, { method: 'POST' })
      await Promise.all([loadTasks(), loadActivity()])
    } catch (err) {
      setError(err.message)
    }
  }

  async function addSubtask(taskId, title) {
    try {
      await api(`/api/tasks/${taskId}/subtasks`, { method: 'POST', body: JSON.stringify({ title }) })
      await loadTasks()
    } catch (err) {
      setError(err.message)
    }
  }

  async function updateDescription(taskId, description) {
    try {
      await api(`/api/tasks/${taskId}`, { method: 'PATCH', body: JSON.stringify({ description }) })
      await loadTasks()
    } catch (err) {
      setError(err.message)
    }
  }

  async function addTagToTask(task, tagName) {
    const name = tagName.trim()
    if (!name) return
    try {
      const existingIds = (task.tags ?? []).map((tag) => tag.id)
      const existingTag = tags.find((tag) => tag.name.toLowerCase() === name.toLowerCase())
      const patch = existingTag
        ? { tag_ids: Array.from(new Set([...existingIds, existingTag.id])) }
        : { tag_ids: existingIds, tag_names: [name] }
      await api(`/api/tasks/${task.id}`, { method: 'PATCH', body: JSON.stringify(patch) })
      await Promise.all([loadTasks(), loadTags()])
    } catch (err) {
      setError(err.message)
    }
  }

  return (
    <div className="app-shell">
      <div className="capture-block">
        <form className="capture-row" onSubmit={captureTask}>
          <input
            value={captureText}
            onChange={(event) => setCaptureText(event.target.value)}
            placeholder="Capture anything..."
            aria-label="Capture a task"
          />
        </form>
      </div>

      <StreakStrip activity={activity} />

      <div className="divider" />

      <div className="tag-filter-row">
        <div className="tag-filter-pills">
          <button
            className={activeTagId === '' ? 'tag-filter-pill active' : 'tag-filter-pill'}
            onClick={() => setActiveTagId('')}
            type="button"
          >
            All
          </button>
          {tags.map((tag) => (
            <button
              className={activeTagId === tag.id ? 'tag-filter-pill active' : 'tag-filter-pill'}
              key={tag.id}
              onClick={() => setActiveTagId(tag.id)}
              type="button"
            >
              {tag.name}
            </button>
          ))}
        </div>
        <label className="show-done">
          <input
            checked={showDone}
            onChange={(event) => setShowDone(event.target.checked)}
            type="checkbox"
          />
          Show done
        </label>
      </div>

      <div className="divider" />

      {error ? <div className="error-box">Backend not reachable: {error}</div> : null}

      <div className="task-table">
        {loading ? <p className="muted">Loading...</p> : null}
        {!loading && !tasks.length ? <p className="muted">Nothing here. Capture a task to get started.</p> : null}
        {tasks.map((task) => (
          <TaskRow
            allTags={tags}
            key={task.id}
            onAddSubtask={addSubtask}
            onAddTag={addTagToTask}
            onToggleComplete={toggleComplete}
            onUpdateDescription={updateDescription}
            task={task}
          />
        ))}
      </div>
    </div>
  )
}

function FlameIcon({ className = '' }) {
  return (
    <svg
      aria-hidden="true"
      className={className}
      fill="none"
      height="16"
      viewBox="0 0 24 24"
      width="16"
      xmlns="http://www.w3.org/2000/svg"
    >
      <path
        d="M12 2c1 3-2 4.5-2 7.5a2 2 0 0 0 4 0c1.2 1 2 2.8 2 4.5a5 5 0 1 1-10 0c0-3.5 2.5-5 3-7 .3-1.2.2-2.7-1-5 1.8.3 3.4 1.5 4 3Z"
        fill="currentColor"
      />
    </svg>
  )
}

function StreakStrip({ activity }) {
  if (!activity) return null
  const days = activity.days ?? []
  const maxCount = Math.max(1, ...days.map((day) => day.count))

  function shade(count) {
    if (!count) return 0
    const ratio = count / maxCount
    if (ratio > 0.75) return 4
    if (ratio > 0.5) return 3
    if (ratio > 0.25) return 2
    return 1
  }

  const todayLabel = days.length
    ? `${formatDayLabel(days[days.length - 1].date)} — ${activity.streak} day${activity.streak === 1 ? '' : 's'} streak`
    : `${activity.streak} day streak`

  return (
    <div className="streak-strip">
      <span className="streak-flame" title={todayLabel}>
        <FlameIcon className="flame-icon" />
        {activity.streak} day{activity.streak === 1 ? '' : 's'} streak
      </span>
      <div className="heatmap-grid">
        {days.map((day) => (
          <span
            className={`heatmap-cell heatmap-shade-${shade(day.count)}`}
            key={day.date}
            title={`${formatDayLabel(day.date)} — ${day.count} task${day.count === 1 ? '' : 's'} done`}
          />
        ))}
      </div>
    </div>
  )
}

function TagTypeahead({ allTags, onPick, onClose }) {
  const [value, setValue] = useState('')
  const suggestions = useMemo(
    () => allTags.filter((tag) => tag.name.toLowerCase().includes(value.trim().toLowerCase())).slice(0, 6),
    [allTags, value],
  )

  function submit(event) {
    event.preventDefault()
    const name = value.trim()
    if (!name) return
    onPick(name)
    setValue('')
    onClose()
  }

  return (
    <form className="tag-typeahead" onSubmit={submit}>
      <input
        autoFocus
        onBlur={() => window.setTimeout(onClose, 120)}
        onChange={(event) => setValue(event.target.value)}
        placeholder="tag name..."
        value={value}
      />
      {suggestions.length ? (
        <div className="tag-typeahead-list">
          {suggestions.map((tag) => (
            <button
              key={tag.id}
              onMouseDown={(event) => {
                event.preventDefault()
                onPick(tag.name)
                onClose()
              }}
              type="button"
            >
              {tag.name}
            </button>
          ))}
        </div>
      ) : null}
    </form>
  )
}

function DescriptionField({ task, onSave }) {
  // Keyed by task.id in the parent, so this remounts (and re-reads the
  // latest description) whenever the row switches to a different task.
  const [value, setValue] = useState(task.description || '')
  const textareaRef = useRef(null)

  useEffect(() => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${el.scrollHeight}px`
  }, [value])

  function handleBlur() {
    const trimmed = value.trim()
    if (trimmed !== (task.description || '')) {
      onSave(trimmed)
    }
  }

  return (
    <textarea
      className="task-description-input"
      onBlur={handleBlur}
      onChange={(event) => setValue(event.target.value)}
      placeholder="Add a description..."
      ref={textareaRef}
      rows={1}
      value={value}
    />
  )
}

function TaskRow({ task, onToggleComplete, onAddSubtask, onAddTag, onUpdateDescription, allTags, nested = false }) {
  const [expanded, setExpanded] = useState(false)
  const [subtaskTitle, setSubtaskTitle] = useState('')
  const [addingTag, setAddingTag] = useState(false)
  const subtasks = task.subtasks ?? []
  const isDone = task.status === 'done'
  // Top-level rows can always expand to reveal a description field and the
  // subtask list/add-form, even when both are currently empty. Subtasks stay
  // one level deep and are never themselves expandable.
  const canExpand = !nested

  async function handleAddSubtask(event) {
    event.preventDefault()
    const title = subtaskTitle.trim()
    if (!title) return
    setSubtaskTitle('')
    await onAddSubtask(task.id, title)
  }

  return (
    <div className={`task-row ${isDone ? 'is-done' : ''} ${nested ? 'task-row-nested' : ''}`}>
      <div className="task-row-main">
        <button
          aria-hidden={!canExpand}
          className={canExpand ? 'task-caret' : 'task-caret task-caret-empty'}
          disabled={!canExpand}
          onClick={() => setExpanded((value) => !value)}
          tabIndex={canExpand ? 0 : -1}
          type="button"
        >
          {canExpand ? (expanded ? '▾' : '▸') : ''}
        </button>
        <button
          aria-label={isDone ? `Mark ${task.title} not done` : `Mark ${task.title} done`}
          className={`task-checkbox ${isDone ? 'checked' : ''}`}
          onClick={() => onToggleComplete(task.id)}
          type="button"
        >
          {isDone ? (
            <svg fill="none" height="10" viewBox="0 0 12 10" width="12">
              <path
                d="M1 5.2 4.2 8.4 11 1.4"
                stroke="white"
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth="2"
              />
            </svg>
          ) : null}
        </button>
        <span className={`task-title ${isDone ? 'task-title-done' : ''}`}>{task.title}</span>
        <span className="task-tags">
          {(task.tags ?? []).map((tag) => (
            <span className="tag-pill" key={tag.id}>{tag.name}</span>
          ))}
          {!nested ? (
            addingTag ? (
              <TagTypeahead
                allTags={allTags}
                onClose={() => setAddingTag(false)}
                onPick={(name) => onAddTag(task, name)}
              />
            ) : (
              <button className="add-tag-btn" onClick={() => setAddingTag(true)} type="button">
                + tag
              </button>
            )
          ) : null}
        </span>
        {task.due_at ? <span className="task-due">{toDateInput(task.due_at)}</span> : null}
      </div>
      {expanded ? (
        <div className="task-expanded">
          <DescriptionField
            key={task.id}
            onSave={(description) => onUpdateDescription(task.id, description)}
            task={task}
          />
          {subtasks.length ? (
            <div className="subtask-list">
              {subtasks.map((subtask) => (
                <TaskRow
                  allTags={allTags}
                  key={subtask.id}
                  nested
                  onAddSubtask={onAddSubtask}
                  onAddTag={onAddTag}
                  onToggleComplete={onToggleComplete}
                  task={subtask}
                />
              ))}
            </div>
          ) : null}
          <form className="subtask-add-form" onSubmit={handleAddSubtask}>
            <input
              onChange={(event) => setSubtaskTitle(event.target.value)}
              placeholder="+ subtask"
              value={subtaskTitle}
            />
          </form>
        </div>
      ) : null}
    </div>
  )
}

export default App
