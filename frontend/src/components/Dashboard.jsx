import { useState, useEffect, useCallback } from 'react'
import { supabase } from '../lib/supabase'

const CATEGORIES = [
  { id: null, label: 'All', dot: null },
  { id: 'work', label: 'Work', dot: 'blue' },
  { id: 'interview_prep', label: 'Interview', dot: 'amber' },
  { id: 'learning', label: 'Learning', dot: 'green' },
  { id: 'personal', label: 'Personal', dot: 'pink' },
  { id: 'hobby', label: 'Hobby', dot: 'purple' },
]

const STATUS_FILTERS = [
  { id: 'active', label: 'Active' },
  { id: 'done', label: 'Done' },
  { id: 'all', label: 'All' },
]

const DOT_COLORS = {
  blue:   'var(--blue)',
  amber:  'var(--amber)',
  green:  'var(--green)',
  pink:   'var(--pink)',
  purple: 'var(--accent)',
}

function priorityColor(priority) {
  if (priority >= 80) return 'var(--red)'
  if (priority >= 50) return 'var(--amber)'
  return 'var(--green)'
}

function cognitiveLoadDot(load) {
  if (load === 'high') return '🔴'
  if (load === 'medium') return '🟡'
  return '🟢'
}

function dueDateStatus(dueDateStr) {
  if (!dueDateStr) return null
  const due = new Date(dueDateStr)
  const now = new Date()
  const diffMs = due - now
  const diffDays = diffMs / (1000 * 60 * 60 * 24)

  if (diffDays < 0) {
    return { label: `Overdue (${due.toLocaleDateString()})`, cls: 'item-card__due--overdue' }
  }
  if (diffDays <= 1) {
    return { label: 'DUE TODAY', cls: 'item-card__due--today' }
  }
  if (diffDays <= 3) {
    return { label: `Due ${due.toLocaleDateString()}`, cls: 'item-card__due--soon' }
  }
  return { label: `Due ${due.toLocaleDateString()}`, cls: 'item-card__due--ok' }
}

function ItemCard({ item, onUpdate }) {
  const [busy, setBusy] = useState(false)

  const handleAction = useCallback(
    async (newStatus) => {
      setBusy(true)
      // Optimistic update
      onUpdate({ ...item, status: newStatus, completed_at: newStatus === 'done' ? new Date().toISOString() : null })

      const update = { status: newStatus }
      if (newStatus === 'done') update.completed_at = new Date().toISOString()
      if (newStatus === 'backlog') update.completed_at = null

      const { error } = await supabase
        .from('items')
        .update(update)
        .eq('id', item.id)

      if (error) {
        console.error('Update failed:', error)
        onUpdate(item)
      }
      setBusy(false)
    },
    [item, onUpdate],
  )

  const dueStatus = dueDateStatus(item.due_date)
  const isDone = item.status === 'done'
  const isArchived = item.status === 'archived'
  const pColor = priorityColor(item.priority ?? 0)
  const progress = item.progress_percent ?? 0

  return (
    <div className="item-card">
      {/* Left priority band */}
      <div className="item-card__band" style={{ background: pColor }} />

      <div className="item-card__body">
        <div className="item-card__title">{item.title}</div>

        <div className="item-card__meta">
          {item.category && (
            <span className="item-card__meta-tag">{item.category.replace('_', ' ')}</span>
          )}
          {item.item_type && (
            <span className="item-card__meta-tag">{item.item_type.replace('_', ' ')}</span>
          )}
          {item.effort_minutes && (
            <span className="item-card__meta-tag">{item.effort_minutes}m</span>
          )}
          {item.cognitive_load && (
            <span title={`Cognitive load: ${item.cognitive_load}`}>
              {cognitiveLoadDot(item.cognitive_load)}
            </span>
          )}
        </div>

        {dueStatus && (
          <div className={`item-card__due ${dueStatus.cls}`}>{dueStatus.label}</div>
        )}

        {item.tags && item.tags.length > 0 && (
          <div className="item-card__tags">
            {item.tags.map((tag, i) => (
              <span key={i} className="item-card__tag">#{tag}</span>
            ))}
          </div>
        )}

        {progress > 0 && (
          <div className="item-card__progress-track">
            <div className="item-card__progress-bar" style={{ width: `${progress}%` }} />
          </div>
        )}

        {!isArchived && (
          <div className="item-card__actions">
            {isDone ? (
              <button
                className="item-card__action-btn item-card__action-btn--reopen"
                onClick={() => handleAction('backlog')}
                disabled={busy}
              >
                ↩ Reopen
              </button>
            ) : (
              <>
                {item.status !== 'in_progress' && (
                  <button
                    className="item-card__action-btn item-card__action-btn--start"
                    onClick={() => handleAction('in_progress')}
                    disabled={busy}
                  >
                    ▶ Start
                  </button>
                )}
                <button
                  className="item-card__action-btn item-card__action-btn--done"
                  onClick={() => handleAction('done')}
                  disabled={busy}
                >
                  ✓ Done
                </button>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

export default function Dashboard() {
  const [items, setItems] = useState([])
  const [categoryFilter, setCategoryFilter] = useState(null)
  const [statusFilter, setStatusFilter] = useState('active')
  const [loading, setLoading] = useState(true)

  const fetchItems = useCallback(async () => {
    setLoading(true)
    let query = supabase.from('items').select('*')

    if (statusFilter === 'active') {
      query = query.in('status', ['backlog', 'today', 'in_progress'])
    } else if (statusFilter === 'done') {
      query = query.eq('status', 'done')
    }

    if (categoryFilter) {
      query = query.eq('category', categoryFilter)
    }

    query = query.order('priority', { ascending: false })

    const { data, error } = await query
    if (!error) {
      setItems(data || [])
    }
    setLoading(false)
  }, [categoryFilter, statusFilter])

  useEffect(() => {
    fetchItems()
  }, [fetchItems])

  // Realtime subscription
  useEffect(() => {
    const channel = supabase
      .channel('dashboard-items')
      .on(
        'postgres_changes',
        { event: '*', schema: 'public', table: 'items' },
        () => {
          fetchItems()
        },
      )
      .subscribe()

    return () => {
      supabase.removeChannel(channel)
    }
  }, [fetchItems])

  const handleUpdate = useCallback((updatedItem) => {
    setItems((prev) =>
      prev.map((it) => (it.id === updatedItem.id ? updatedItem : it)),
    )
  }, [])

  return (
    <div className="dashboard">
      <div className="dashboard__header">
        {/* Category filter */}
        <div className="dashboard__filters">
          {CATEGORIES.map((cat) => (
            <button
              key={String(cat.id)}
              className={`dashboard__filter-btn ${categoryFilter === cat.id ? 'dashboard__filter-btn--active' : ''}`}
              onClick={() => setCategoryFilter(cat.id)}
            >
              {cat.dot && (
                <span
                  className="dashboard__filter-dot"
                  style={{ background: DOT_COLORS[cat.dot] }}
                />
              )}
              {cat.label}
            </button>
          ))}
        </div>

        {/* Status row */}
        <div className="dashboard__status-row">
          {STATUS_FILTERS.map((sf) => (
            <button
              key={sf.id}
              className={`dashboard__status-btn ${statusFilter === sf.id ? 'dashboard__status-btn--active' : ''}`}
              onClick={() => setStatusFilter(sf.id)}
            >
              {sf.label}
            </button>
          ))}
        </div>
      </div>

      <div className="dashboard__content">
        {loading ? (
          <div className="dashboard__loading">
            {[1, 2, 3].map((i) => (
              <div key={i} className="skeleton" />
            ))}
          </div>
        ) : items.length === 0 ? (
          <div className="dashboard__empty">
            <div className="dashboard__empty-icon">📭</div>
            <div>No items here. Add one in <strong>Capture ✚</strong> or chat.</div>
          </div>
        ) : (
          <div className="dashboard__grid">
            {items.map((item) => (
              <ItemCard key={item.id} item={item} onUpdate={handleUpdate} />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
