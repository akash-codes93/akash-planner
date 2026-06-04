import { useState, useEffect, useCallback } from 'react'
import { supabase } from '../lib/supabase'

const CATEGORIES = [
  { id: null, label: 'All' },
  { id: 'work', label: 'Work' },
  { id: 'interview_prep', label: 'Interview Prep' },
  { id: 'learning', label: 'Learning' },
  { id: 'personal', label: 'Personal' },
  { id: 'hobby', label: 'Hobby' },
]

const STATUS_FILTERS = [
  { id: 'active', label: 'Active' },
  { id: 'done', label: 'Done' },
  { id: 'all', label: 'All' },
]

function priorityClass(priority) {
  if (priority >= 80) return 'item-card__priority--high'
  if (priority >= 50) return 'item-card__priority--medium'
  return 'item-card__priority--low'
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
        // Revert on error
        onUpdate(item)
      }
      setBusy(false)
    },
    [item, onUpdate],
  )

  const dueStatus = dueDateStatus(item.due_date)
  const isDone = item.status === 'done'
  const isArchived = item.status === 'archived'

  return (
    <div className="item-card">
      <div className="item-card__top">
        <span className={`item-card__priority ${priorityClass(item.priority ?? 0)}`}>
          {item.priority ?? 0}
        </span>
        <span className="item-card__title">{item.title}</span>
      </div>

      <div className="item-card__meta">
        {item.category && (
          <span className="item-card__pill">{item.category.replace('_', ' ')}</span>
        )}
        {item.item_type && (
          <span className="item-card__pill">{item.item_type.replace('_', ' ')}</span>
        )}
        {item.effort_minutes && (
          <span className="item-card__effort">{item.effort_minutes}m</span>
        )}
        {item.cognitive_load && (
          <span className="item-card__load" title={`Cognitive load: ${item.cognitive_load}`}>
            {cognitiveLoadDot(item.cognitive_load)}
          </span>
        )}
        {dueStatus && (
          <span className={`item-card__due ${dueStatus.cls}`}>{dueStatus.label}</span>
        )}
      </div>

      {item.tags && item.tags.length > 0 && (
        <div className="item-card__tags">
          {item.tags.map((tag, i) => (
            <span key={i} className="item-card__tag">#{tag}</span>
          ))}
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
    // 'all' — no status filter

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
        <div className="dashboard__title">items</div>

        <div className="dashboard__filters">
          {CATEGORIES.map((cat) => (
            <button
              key={String(cat.id)}
              className={`dashboard__filter-btn ${categoryFilter === cat.id ? 'dashboard__filter-btn--active' : ''}`}
              onClick={() => setCategoryFilter(cat.id)}
            >
              {cat.label}
            </button>
          ))}
        </div>

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
            {[1, 2, 3, 4].map((i) => (
              <div key={i} className="skeleton" />
            ))}
          </div>
        ) : items.length === 0 ? (
          <div className="dashboard__empty">
            <span className="dashboard__empty-icon">📭</span>
            <div>No items. Add one in Capture or chat with the agent.</div>
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
