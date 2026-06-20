import { useEffect, useState } from 'react'
import './App.css'
import workmapLogo from './assets/workmap-logo.png'

const API_BASE = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000'

const columns = [
  { key: 'backlog', label: 'Backlog' },
  { key: 'next', label: 'Next' },
  { key: 'doing', label: 'Doing' },
  { key: 'blocked', label: 'Blocked' },
  { key: 'done', label: 'Done' },
]

const statusLabels = Object.fromEntries(columns.map((column) => [column.key, column.label]))

function routeFromHash() {
  const hash = window.location.hash.replace(/^#/, '') || '/'
  const parts = hash.split('/').filter(Boolean)
  if (parts[0] === 'goals' && parts[1] && parts[2] === 'settings') return { page: 'goal-settings', id: parts[1] }
  if (parts[0] === 'goals' && parts[1]) return { page: 'goal', id: parts[1] }
  if (parts[0] === 'tasks' && parts[1]) return { page: 'task', id: parts[1] }
  if (parts[0] === 'planning') return { page: 'planning' }
  if (parts[0] === 'ai') return { page: 'ai' }
  return { page: 'dashboard' }
}

function navigate(path) {
  window.location.hash = path
}


async function api(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  })
  if (!response.ok) {
    const body = await response.text()
    throw new Error(body || `Request failed: ${response.status}`)
  }
  return response.status === 204 ? null : response.json()
}

function minutes(value) {
  const total = Number(value || 0)
  if (total < 60) return `${total}m`
  const hours = Math.floor(total / 60)
  const mins = total % 60
  return mins ? `${hours}h ${mins}m` : `${hours}h`
}

function toDateInput(value) {
  if (!value) return ''
  return String(value).slice(0, 10)
}

function numberValue(value, fallback = 0) {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : fallback
}

function App() {
  const [route, setRoute] = useState(routeFromHash)
  const [dashboard, setDashboard] = useState(null)
  const [goal, setGoal] = useState(null)
  const [task, setTask] = useState(null)
  const [planning, setPlanning] = useState(null)
  const [boardMode, setBoardMode] = useState('board')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [quickTask, setQuickTask] = useState('')
  const [quickTaskGoal, setQuickTaskGoal] = useState('')
  const [quickGoal, setQuickGoal] = useState('')
  const [goalTaskTitle, setGoalTaskTitle] = useState('')
  const [aiInput, setAiInput] = useState('')
  const [aiDraft, setAiDraft] = useState(null)
  const [aiRunning, setAiRunning] = useState(false)
  const [aiLog, setAiLog] = useState([
    {
      type: 'summary',
      title: 'What I can do',
      text: 'Create goals, create backlog tasks, add tasks inside the current goal, summarize, suggest next tasks, and complete the current task after confirmation.',
    },
  ])
  const [notice, setNotice] = useState(null)

  function notify(message, tone = 'success') {
    setNotice({ message, tone, id: Date.now() })
    window.clearTimeout(notify.timer)
    notify.timer = window.setTimeout(() => setNotice(null), 3200)
  }

  function goWithNotice(path, message, tone = 'success') {
    navigate(path)
    window.setTimeout(() => notify(message, tone), 80)
  }

  useEffect(() => {
    const onHashChange = () => setRoute(routeFromHash())
    window.addEventListener('hashchange', onHashChange)
    return () => window.removeEventListener('hashchange', onHashChange)
  }, [])


  useEffect(() => {
    loadRoute()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [route.page, route.id])

  async function loadRoute() {
    setLoading(true)
    setError('')
    try {
      const overview = await api('/api/dashboard')
      setDashboard(overview)
      if (route.page === 'goal' || route.page === 'goal-settings') {
        setGoal(await api(`/api/goals/${route.id}`))
      } else {
        setGoal(null)
      }
      if (route.page === 'task') {
        setTask(await api(`/api/tasks/${route.id}`))
      } else {
        setTask(null)
      }
      if (route.page === 'planning') {
        setPlanning(await api('/api/planning/due'))
      }
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  async function createGoal(event) {
    event.preventDefault()
    if (!quickGoal.trim()) return
    const created = await api('/api/goals', {
      method: 'POST',
      body: JSON.stringify({ title: quickGoal.trim(), priority: 60 }),
    })
    setQuickGoal('')
    goWithNotice(`/goals/${created.id}`, `Goal created: ${created.title}`)
  }

  async function createTopTask(event) {
    event.preventDefault()
    if (!quickTask.trim()) return
    const created = await api('/api/tasks', {
      method: 'POST',
      body: JSON.stringify({
        title: quickTask.trim(),
        goal_id: quickTaskGoal || null,
        status: 'backlog',
        priority: 50,
        estimate_minutes: 30,
      }),
    })
    setQuickTask('')
    goWithNotice(`/tasks/${created.id}`, `Task created in ${created.goal_title ?? 'Inbox'}: ${created.title}`)
  }

  async function createGoalTask(event, goalId) {
    event.preventDefault()
    if (!goalTaskTitle.trim()) return
    const created = await api('/api/tasks', {
      method: 'POST',
      body: JSON.stringify({
        title: goalTaskTitle.trim(),
        goal_id: goalId,
        status: 'backlog',
        priority: 50,
        estimate_minutes: 30,
      }),
    })
    setGoalTaskTitle('')
    goWithNotice(`/tasks/${created.id}`, `Task added to goal: ${created.title}`)
  }

  async function updateTask(taskId, patch) {
    const updated = await api(`/api/tasks/${taskId}`, {
      method: 'PATCH',
      body: JSON.stringify(patch),
    })
    setTask(updated)
    await loadRoute()
    notify(`Task updated: ${updated.title}`)
    return updated
  }

  async function updateGoal(goalId, patch) {
    const updated = await api(`/api/goals/${goalId}`, {
      method: 'PATCH',
      body: JSON.stringify(patch),
    })
    setGoal((current) => (current?.id === goalId ? { ...current, ...updated } : current))
    await loadRoute()
    notify(`Goal updated: ${updated.title}`)
    return updated
  }

  async function addProgress(taskId, payload) {
    const updated = await api(`/api/tasks/${taskId}/progress`, {
      method: 'POST',
      body: JSON.stringify(payload),
    })
    setTask(updated)
    await loadRoute()
    notify(`Progress saved for ${updated.title}`)
  }

  async function completeTask(taskId) {
    const updated = await api(`/api/tasks/${taskId}/complete`, { method: 'POST' })
    setTask(updated)
    await loadRoute()
    notify(`Task completed: ${updated.title}`)
  }

  async function archiveTask(taskId) {
    await api(`/api/tasks/${taskId}/archive`, { method: 'POST' })
    notify('Task archived')
    navigate('/')
    await loadRoute()
  }

  async function deleteTask(taskId) {
    if (!window.confirm('Delete this task permanently? This cannot be undone.')) return
    await api(`/api/tasks/${taskId}`, { method: 'DELETE' })
    notify('Task deleted')
    navigate('/')
    await loadRoute()
  }

  function currentAiContext() {
    if (route.page === 'goal') return { goal_id: route.id }
    if (route.page === 'task') return { task_id: route.id, goal_id: task?.goal_id }
    return {}
  }

  async function runAiCommand(event) {
    event?.preventDefault()
    if (!aiInput.trim() || aiRunning) return
    setAiRunning(true)
    try {
      const draft = await api('/api/ai/command', {
        method: 'POST',
        body: JSON.stringify({ input_text: aiInput.trim(), context: currentAiContext() }),
      })
      if (draft.action_type === 'summarize' || draft.action_type === 'suggest_next') {
        setAiDraft(null)
        setAiLog((items) => [formatAiAnswer(draft), ...items].slice(0, 6))
      } else {
        setAiDraft(draft)
        setAiLog((items) => [{ type: 'status', text: `Prepared ${draft.action_type}. Review the preview before confirming.` }, ...items].slice(0, 6))
      }
      notify('AI planner response ready')
      setAiInput('')
    } catch (err) {
      notify(`AI planner failed: ${err.message}`, 'error')
    } finally {
      setAiRunning(false)
    }
  }

  async function confirmAiDraft() {
    if (!aiDraft) return
    const result = await api(`/api/ai/actions/${aiDraft.id}/confirm`, {
      method: 'POST',
      body: JSON.stringify({ overrides: currentAiContext() }),
    })
    setAiDraft(null)
    setAiLog((items) => [{ type: 'status', text: `Confirmed ${result.action_type}.` }, ...items].slice(0, 6))
    await loadRoute()
    const created = result.result
    if (result.action_type === 'create_goal' && created?.id) navigate(`/goals/${created.id}`)
    if (result.action_type === 'create_task' && created?.id) navigate(`/tasks/${created.id}`)
  }

  async function clearWorkspace() {
    if (!window.confirm('Clear all local Workmap goals and tasks? This cannot be undone.')) return
    await api('/api/workspace/clear', { method: 'POST' })
    setGoal(null)
    setTask(null)
    setPlanning(null)
    setAiDraft(null)
    setAiLog([{ type: 'status', text: 'Workspace cleared. Create your own goals and backlog tasks to start fresh.' }])
    navigate('/')
    await loadRoute()
  }

  const goals = dashboard?.goals ?? []

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <button className="brand" onClick={() => navigate('/')} type="button">
          <WorkmapLogo />
          <strong>Workmap</strong>
        </button>
        <nav className="nav-list">
          <button className={route.page === 'dashboard' ? 'active' : ''} onClick={() => navigate('/')} type="button">Dashboard</button>
          <button className={route.page === 'planning' ? 'active' : ''} onClick={() => navigate('/planning')} type="button">Planning</button>
          <button className={route.page === 'ai' ? 'active' : ''} onClick={() => navigate('/ai')} type="button">AI Planner</button>
        </nav>
        <div className="sidebar-section">
          <p>Goals</p>
          {goals.map((item) => (
            <button
              className={route.page === 'goal' && route.id === item.id ? 'goal-link active' : 'goal-link'}
              key={item.id}
              onClick={() => navigate(`/goals/${item.id}`)}
              type="button"
            >
              <span>{item.title}</span>
              <small>{Math.round(item.calculated_progress ?? item.progress_percent)}%</small>
            </button>
          ))}
        </div>
        <form className="sidebar-form" onSubmit={createGoal}>
          <input value={quickGoal} onChange={(event) => setQuickGoal(event.target.value)} placeholder="+ New goal" />
        </form>
        <button className="clear-workspace" onClick={clearWorkspace} type="button">Clear local data</button>
      </aside>

      <main className="workspace">
        <TopBar
          quickTask={quickTask}
          setQuickTask={setQuickTask}
          quickTaskGoal={quickTaskGoal}
          setQuickTaskGoal={setQuickTaskGoal}
          goals={goals}
          createTopTask={createTopTask}
        />
        {error ? <div className="error-box">Backend not reachable: {error}</div> : null}
        {loading ? <div className="loading">Loading Workmap...</div> : null}
        {!loading && route.page === 'dashboard' ? <DashboardPage dashboard={dashboard} /> : null}
        {!loading && route.page === 'planning' ? <PlanningPage planning={planning ?? dashboard?.due} /> : null}
        {!loading && route.page === 'goal' && goal ? (
          <GoalPage
            key={goal.id}
            goal={goal}
            boardMode={boardMode}
            setBoardMode={setBoardMode}
            goalTaskTitle={goalTaskTitle}
            setGoalTaskTitle={setGoalTaskTitle}
            createGoalTask={createGoalTask}
            updateTask={updateTask}
            updateGoal={updateGoal}
          />
        ) : null}
        {!loading && route.page === 'goal-settings' && goal ? (
          <GoalSettingsPage key={goal.id} goal={goal} updateGoal={updateGoal} />
        ) : null}
        {!loading && route.page === 'task' && task ? (
          <TaskPage
            key={task.id}
            task={task}
            goals={goals}
            updateTask={updateTask}
            addProgress={addProgress}
            completeTask={completeTask}
            archiveTask={archiveTask}
            deleteTask={deleteTask}
          />
        ) : null}
        {!loading && route.page === 'ai' ? (
          <AiPage
            aiLog={aiLog}
            aiDraft={aiDraft}
            aiInput={aiInput}
            aiRunning={aiRunning}
            setAiInput={setAiInput}
            runAiCommand={runAiCommand}
            confirmAiDraft={confirmAiDraft}
            setAiDraft={setAiDraft}
          />
        ) : null}
      </main>

      <aside className="ai-rail">
        <AiPanel
          aiLog={aiLog}
          aiDraft={aiDraft}
          aiInput={aiInput}
          aiRunning={aiRunning}
          setAiInput={setAiInput}
          runAiCommand={runAiCommand}
          confirmAiDraft={confirmAiDraft}
          setAiDraft={setAiDraft}
        />
      </aside>
      {notice ? <div className={`toast toast-${notice.tone}`}>{notice.message}</div> : null}
    </div>
  )
}

function WorkmapLogo() {
  return (
    <span className="workmap-logo">
      <img src={workmapLogo} alt="" />
    </span>
  )
}

function TopBar({ quickTask, setQuickTask, quickTaskGoal, setQuickTaskGoal, goals, createTopTask }) {
  return (
    <header className="topbar">
      <form className="quick-create" onSubmit={createTopTask}>
        <input value={quickTask} onChange={(event) => setQuickTask(event.target.value)} placeholder="Quick add backlog task..." />
        <select value={quickTaskGoal} onChange={(event) => setQuickTaskGoal(event.target.value)} aria-label="Task goal">
          <option value="">Inbox / no goal</option>
          {goals.map((goal) => (
            <option key={goal.id} value={goal.id}>{goal.title}</option>
          ))}
        </select>
        <button type="submit">+ Task</button>
      </form>
    </header>
  )
}

function DashboardPage({ dashboard }) {
  const stats = dashboard?.stats ?? {}
  return (
    <section className="page">
      <PageHeader eyebrow="Dashboard" title="Global workspace" subtitle="Goals, active tasks, due pressure, and the next useful picks." />
      <div className="metric-row">
        <Metric label="Goals" value={stats.goals ?? 0} />
        <Metric label="Active tasks" value={stats.active_tasks ?? 0} />
        <Metric label="Due soon" value={stats.due_soon ?? 0} tone="attention" />
        <Metric label="Stale" value={stats.stale ?? 0} tone={stats.stale ? 'danger' : ''} />
        <Metric label="Blocked" value={stats.blocked_tasks ?? 0} tone={stats.blocked_tasks ? 'danger' : ''} />
        <Metric label="Focus logged" value={minutes(stats.logged_minutes)} />
      </div>

      <div className="two-column">
        <section className="card">
          <SectionTitle title="Goals" action="Open a goal to see board, list, and timeline" />
          <div className="table-list">
            {(dashboard?.goals ?? []).map((goal) => (
              <button className="row-item" key={goal.id} onClick={() => navigate(`/goals/${goal.id}`)} type="button">
                <span>
                  <strong>{goal.title}</strong>
                  <small>{goal.task_count} tasks</small>
                </span>
                <Progress value={goal.calculated_progress ?? goal.progress_percent} />
              </button>
            ))}
          </div>
        </section>

        <section className="card">
          <SectionTitle title="Suggested next" action="Priority, status, due date, and quick wins" />
          <TaskList tasks={dashboard?.next_tasks ?? []} />
        </section>
      </div>

      <section className="card">
        <SectionTitle title="Recent tasks" action="Compact scan" />
        <TaskTable tasks={dashboard?.recent_tasks ?? []} />
      </section>
    </section>
  )
}

function PlanningPage({ planning }) {
  const buckets = [
    ['overdue', 'Overdue'],
    ['due_soon', 'Due soon'],
    ['stale', 'Dragged / stale'],
    ['no_due_date', 'No due date'],
  ]
  return (
    <section className="page">
      <PageHeader eyebrow="Planning" title="Due dates, not day-only planning" subtitle="Use dates and stale signals when tasks drag across multiple days." />
      <div className="planning-grid">
        {buckets.map(([key, title]) => (
          <section className="card" key={key}>
            <SectionTitle title={title} action={`${planning?.[key]?.length ?? 0} tasks`} />
            <TaskList tasks={planning?.[key] ?? []} />
          </section>
        ))}
      </div>
    </section>
  )
}

function GoalPage({ goal, boardMode, setBoardMode, goalTaskTitle, setGoalTaskTitle, createGoalTask, updateTask }) {
  const tasks = goal.tasks ?? []
  const timelineTasks = tasks.filter((item) => item.progress_percent > 0 || item.status === 'done')

  return (
    <section className="page">
      <PageHeader
        eyebrow="Goal"
        title={goal.title}
        subtitle={`${tasks.length} tasks · ${Math.round(goal.calculated_progress ?? goal.progress_percent ?? 0)}% complete`}
        action={<button aria-label="Edit goal" className="icon-button" onClick={() => navigate(`/goals/${goal.id}/settings`)} title="Edit goal" type="button">✎</button>}
      />
      <div className="goal-toolbar">
        <div className="segmented">
            <button className={boardMode === 'board' ? 'active' : ''} onClick={() => setBoardMode('board')} type="button">Board</button>
            <button className={boardMode === 'list' ? 'active' : ''} onClick={() => setBoardMode('list')} type="button">List</button>
            <button className={boardMode === 'timeline' ? 'active' : ''} onClick={() => setBoardMode('timeline')} type="button">Timeline</button>
        </div>
        <form className="inline-create" onSubmit={(event) => createGoalTask(event, goal.id)}>
          <input value={goalTaskTitle} onChange={(event) => setGoalTaskTitle(event.target.value)} placeholder={`Add backlog task to ${goal.title}...`} />
          <button type="submit">Add task</button>
        </form>
      </div>

      {boardMode === 'board' ? <GoalBoard tasks={tasks} updateTask={updateTask} /> : null}
      {boardMode === 'list' ? (
        <section className="card">
          <TaskTable tasks={tasks} />
        </section>
      ) : null}
      {boardMode === 'timeline' ? (
        <section className="card">
          <SectionTitle title="Progress timeline" action="Tasks with recorded progress" />
          <div className="timeline-list">
            {timelineTasks.map((task) => (
              <button className="timeline-row" key={task.id} onClick={() => navigate(`/tasks/${task.id}`)} type="button">
                <strong>{task.title}</strong>
                <span>{task.progress_percent}% · {statusLabels[task.status]}</span>
              </button>
            ))}
          </div>
        </section>
      ) : null}
    </section>
  )
}


function GoalSettingsPage({ goal, updateGoal }) {
  const [goalDraft, setGoalDraft] = useState({
    title: goal.title ?? '',
    description: goal.description ?? '',
    priority: goal.priority ?? 50,
    status: goal.status ?? 'active',
  })

  async function saveGoal(event) {
    event.preventDefault()
    await updateGoal(goal.id, {
      title: goalDraft.title,
      description: goalDraft.description,
      priority: numberValue(goalDraft.priority, 50),
      status: goalDraft.status,
    })
  }

  return (
    <section className="page">
      <PageHeader eyebrow="Goal settings" title={goal.title} subtitle="Edit goal metadata separately from the task board." />
      <section className="card goal-editor">
        <div className="settings-intro">
          <strong>Goal details</strong>
          <span>Keep goal metadata separate from the task board so the board stays focused.</span>
        </div>
        <form className="goal-edit-form" onSubmit={saveGoal}>
          <label className="span-2">
            Goal name
            <input value={goalDraft.title} onChange={(event) => setGoalDraft({ ...goalDraft, title: event.target.value })} />
          </label>
          <label>
            Status
            <select value={goalDraft.status} onChange={(event) => setGoalDraft({ ...goalDraft, status: event.target.value })}>
              <option value="active">Active</option>
              <option value="paused">Paused</option>
              <option value="done">Done</option>
            </select>
          </label>
          <label>
            Priority
            <input type="number" min="0" max="100" value={goalDraft.priority} onChange={(event) => setGoalDraft({ ...goalDraft, priority: event.target.value })} />
          </label>
          <label className="span-3">
            Description
            <textarea value={goalDraft.description} onChange={(event) => setGoalDraft({ ...goalDraft, description: event.target.value })} />
          </label>
          <div className="form-actions span-2">
            <button type="submit">Save goal</button>
            <button className="secondary-button" onClick={() => navigate(`/goals/${goal.id}`)} type="button">Cancel</button>
          </div>
        </form>
      </section>
    </section>
  )
}

function GoalBoard({ tasks, updateTask }) {
  return (
    <div className="board">
      {columns.map((column) => {
        const items = tasks.filter((task) => task.status === column.key)
        return (
          <section className={`board-column board-column-${column.key}`} key={column.key}>
            <header>
              <strong>{column.label}</strong>
              <span>{items.length}</span>
            </header>
            <div className="board-stack">
              {items.map((task) => (
                <article className={`issue-card status-${task.status}`} key={task.id}>
                  <button className="issue-title" onClick={() => navigate(`/tasks/${task.id}`)} type="button">
                    {task.title}
                  </button>
                  <div className="issue-meta">
                    <span>{task.type}</span>
                    <span>P{task.priority}</span>
                    <span>{minutes(task.estimate_minutes)}</span>
                    {task.due_at ? <span>Due {toDateInput(task.due_at)}</span> : null}
                  </div>
                  <Progress value={task.progress_percent} />
                  <select value={task.status} onChange={(event) => updateTask(task.id, { status: event.target.value })}>
                    {columns.map((item) => (
                      <option key={item.key} value={item.key}>{item.label}</option>
                    ))}
                  </select>
                </article>
              ))}
            </div>
          </section>
        )
      })}
    </div>
  )
}

function TaskPage({ task, goals, updateTask, addProgress, completeTask, archiveTask, deleteTask }) {
  const [draft, setDraft] = useState(() => taskToDraft(task))
  const [progressDraft, setProgressDraft] = useState({ progress_delta: 20, minutes: 25, summary: '' })

  function patchFromDraft() {
    return {
      title: draft.title,
      description: draft.description,
      goal_id: draft.goal_id || null,
      status: draft.status,
      type: draft.type,
      priority: numberValue(draft.priority, 50),
      estimate_minutes: numberValue(draft.estimate_minutes, 30),
      logged_minutes: numberValue(draft.logged_minutes, 0),
      progress_percent: numberValue(draft.progress_percent, 0),
      due_at: draft.due_at || null,
      tags: draft.tags.split(',').map((item) => item.trim()).filter(Boolean),
    }
  }

  async function saveTask(event) {
    event.preventDefault()
    await updateTask(task.id, patchFromDraft())
  }

  async function saveProgress(event) {
    event.preventDefault()
    await addProgress(task.id, {
      progress_delta: numberValue(progressDraft.progress_delta, 20),
      minutes: numberValue(progressDraft.minutes, 25),
      summary: progressDraft.summary || `Added ${progressDraft.progress_delta}% progress.`,
    })
    setProgressDraft({ progress_delta: 20, minutes: 25, summary: '' })
  }

  return (
    <section className="page">
      <PageHeader eyebrow={task.goal_title ? `Goal: ${task.goal_title}` : 'Inbox / no goal'} title={task.title} subtitle={task.description || 'No description yet.'} />
      <div className="task-layout">
        <section className="card task-main">
          <SectionTitle title="Task details" action="Edit fields directly" />
          <form className="task-edit-form" onSubmit={saveTask}>
            <label>
              Title
              <input value={draft.title} onChange={(event) => setDraft({ ...draft, title: event.target.value })} />
            </label>
            <label>
              Goal
              <select value={draft.goal_id} onChange={(event) => setDraft({ ...draft, goal_id: event.target.value })}>
                <option value="">Inbox / no goal</option>
                {goals.map((goal) => (
                  <option key={goal.id} value={goal.id}>{goal.title}</option>
                ))}
              </select>
            </label>
            <label className="span-2">
              Description
              <textarea value={draft.description} onChange={(event) => setDraft({ ...draft, description: event.target.value })} />
            </label>
            <label>
              Status
              <select value={draft.status} onChange={(event) => setDraft({ ...draft, status: event.target.value })}>
                {columns.map((item) => (
                  <option key={item.key} value={item.key}>{item.label}</option>
                ))}
              </select>
            </label>
            <label>
              Type
              <input value={draft.type} onChange={(event) => setDraft({ ...draft, type: event.target.value })} />
            </label>
            <label>
              Priority
              <input type="number" min="0" max="100" value={draft.priority} onChange={(event) => setDraft({ ...draft, priority: event.target.value })} />
            </label>
            <label>
              Estimate minutes
              <input type="number" min="1" value={draft.estimate_minutes} onChange={(event) => setDraft({ ...draft, estimate_minutes: event.target.value })} />
            </label>
            <label>
              Manual logged minutes
              <input type="number" min="0" value={draft.logged_minutes} onChange={(event) => setDraft({ ...draft, logged_minutes: event.target.value })} />
            </label>
            <label>
              Progress %
              <input type="number" min="0" max="100" value={draft.progress_percent} onChange={(event) => setDraft({ ...draft, progress_percent: event.target.value })} />
            </label>
            <label>
              Due date
              <input type="date" value={draft.due_at} onChange={(event) => setDraft({ ...draft, due_at: event.target.value })} />
            </label>
            <label>
              Tags
              <input value={draft.tags} onChange={(event) => setDraft({ ...draft, tags: event.target.value })} placeholder="redis, interview" />
            </label>
            <div className="form-actions span-2">
              <button type="submit">Save task</button>
              <button type="button" onClick={() => completeTask(task.id)}>Complete</button>
              <button className="secondary-button" type="button" onClick={() => archiveTask(task.id)}>Archive</button>
              <button className="danger-button" type="button" onClick={() => deleteTask(task.id)}>Delete</button>
            </div>
          </form>
        </section>

        <section className="card">
          <SectionTitle title="Progress and focus" action={`${minutes(task.total_logged_minutes)} logged`} />
          <Progress value={task.progress_percent} large />
          <form className="progress-form" onSubmit={saveProgress}>
            <label>
              Progress added
              <input type="number" min="1" max="100" value={progressDraft.progress_delta} onChange={(event) => setProgressDraft({ ...progressDraft, progress_delta: event.target.value })} />
            </label>
            <label>
              Minutes
              <input type="number" min="1" value={progressDraft.minutes} onChange={(event) => setProgressDraft({ ...progressDraft, minutes: event.target.value })} />
            </label>
            <label className="span-2">
              What did you actually do?
              <textarea value={progressDraft.summary} onChange={(event) => setProgressDraft({ ...progressDraft, summary: event.target.value })} placeholder="No invented notes. Write what happened in this session." />
            </label>
            <button type="submit">Save progress</button>
          </form>
          <div className="session-list">
            {(task.sessions ?? []).map((session) => (
              <article className="session-row" key={session.id}>
                <strong>+{session.progress_delta}% · {minutes(session.duration_minutes)}</strong>
                <p>{session.summary}</p>
              </article>
            ))}
            {!task.sessions?.length ? <p className="muted">No focus sessions yet.</p> : null}
          </div>
        </section>
      </div>
    </section>
  )
}

function taskToDraft(task) {
  return {
    title: task.title ?? '',
    description: task.description ?? '',
    goal_id: task.goal_id ?? '',
    status: task.status ?? 'backlog',
    type: task.type ?? 'task',
    priority: task.priority ?? 50,
    estimate_minutes: task.estimate_minutes ?? 30,
    logged_minutes: task.logged_minutes ?? 0,
    progress_percent: task.progress_percent ?? 0,
    due_at: toDateInput(task.due_at),
    tags: (task.tags ?? []).join(', '),
  }
}

function AiPage(props) {
  return (
    <section className="page">
      <PageHeader eyebrow="AI Planner" title="Command, preview, confirm" subtitle="Uses local Ollama when available, with deterministic fallback. Mutations require confirmation." />
      <section className="card">
        <CapabilityList />
        <AiPanel {...props} expanded />
      </section>
    </section>
  )
}

function CapabilityList() {
  const items = [
    'Create goals',
    'Create backlog tasks',
    'Add tasks inside the current goal',
    'Complete the current task',
    'Suggest which task to pick next',
    'Summarize the planner',
    'Draft due-date, estimate, and priority changes',
  ]
  return (
    <div className="capability-grid">
      {items.map((item) => <span key={item}>{item}</span>)}
    </div>
  )
}

function AiPanel({ aiLog, aiDraft, aiInput, aiRunning, setAiInput, runAiCommand, confirmAiDraft, setAiDraft, expanded = false }) {
  return (
    <div className={expanded ? 'ai-panel expanded' : 'ai-panel'}>
      <SectionTitle title="Planner AI" action="Try: what can you do?" />
      <form className="ai-form" onSubmit={runAiCommand}>
        <input disabled={aiRunning} value={aiInput} onChange={(event) => setAiInput(event.target.value)} placeholder="create task..., create goal..., summarize, suggest next" />
        <button className={aiRunning ? 'running' : ''} disabled={aiRunning} type="submit">
          {aiRunning ? 'Working...' : 'Run'}
        </button>
      </form>
      {aiRunning ? <div className="ai-runner"><span /> Thinking with local planner context...</div> : null}
      {aiDraft ? (
        <div className="draft-box">
          <p>Draft: <strong>{aiDraft.action_type}</strong></p>
          <pre>{JSON.stringify(aiDraft.payload, null, 2)}</pre>
          <div className="button-row">
            <button onClick={confirmAiDraft} type="button">Confirm</button>
            <button className="secondary-button" onClick={() => setAiDraft(null)} type="button">Cancel</button>
          </div>
        </div>
      ) : null}
      <div className="ai-log">
        {aiLog.map((item, index) => (
          <AiLogItem item={item} key={`${JSON.stringify(item)}-${index}`} />
        ))}
      </div>
    </div>
  )
}

function formatAiAnswer(draft) {
  if (draft.action_type === 'suggest_next') {
    const tasks = draft.payload?.tasks ?? []
    if (!tasks.length) {
      return {
        type: 'summary',
        title: 'No clear next task',
        text: 'Add backlog tasks, due dates, or priorities to improve suggestions.',
      }
    }
    return {
      type: 'suggestions',
      title: 'Planner suggestion',
      text: 'Based on priority, status, progress, due dates, and quick-win score, pick from these next.',
      tasks: tasks.slice(0, 3),
    }
  }
  if (draft.action_type === 'summarize') {
    return {
      type: 'summary',
      title: 'Planner summary',
      text: draft.payload?.summary ?? 'No summary available.',
    }
  }
  return { type: 'status', text: `${draft.action_type}: ${JSON.stringify(draft.payload)}` }
}

function AiLogItem({ item }) {
  if (typeof item === 'string') {
    return <p>{item}</p>
  }
  if (item.type === 'suggestions') {
    return (
      <article className="ai-answer-card">
        <strong>{item.title}</strong>
        <span>{item.text}</span>
        <ol>
          {item.tasks.map((task) => (
            <li key={task.id}>
              <button onClick={() => navigate(`/tasks/${task.id}`)} type="button">
                <b>{task.title}</b>
                <small>{task.goal_title ?? 'Inbox'} · {task.progress_percent}% done · P{task.priority}</small>
              </button>
            </li>
          ))}
        </ol>
      </article>
    )
  }
  if (item.type === 'summary') {
    return (
      <article className="ai-answer-card">
        <strong>{item.title}</strong>
        <span>{item.text}</span>
      </article>
    )
  }
  return <p>{item.text}</p>
}

function PageHeader({ eyebrow, title, subtitle, action = null }) {
  return (
    <header className="page-header">
      <div>
        <p>{eyebrow}</p>
        <h1>{title}</h1>
        <span>{subtitle}</span>
      </div>
      {action ? <div className="page-header-action">{action}</div> : null}
    </header>
  )
}

function Metric({ label, value, tone = '' }) {
  return (
    <div className={`metric ${tone}`}>
      <strong>{value}</strong>
      <span>{label}</span>
    </div>
  )
}

function SectionTitle({ title, action }) {
  return (
    <div className="section-title">
      <h2>{title}</h2>
      <span>{action}</span>
    </div>
  )
}

function Progress({ value, large = false }) {
  const safeValue = Math.max(0, Math.min(100, Number(value || 0)))
  return (
    <div className={large ? 'progress large' : 'progress'} aria-label={`${safeValue}% complete`}>
      <span style={{ width: `${safeValue}%` }} />
    </div>
  )
}

function TaskList({ tasks }) {
  return (
    <div className="task-list">
      {tasks.map((task) => (
        <button className="task-row" key={task.id} onClick={() => navigate(`/tasks/${task.id}`)} type="button">
          <span>
            <strong>{task.title}</strong>
            <small>{task.goal_title ?? 'Inbox'} · {statusLabels[task.status]} · {task.due_at ? `Due ${toDateInput(task.due_at)}` : 'No due date'}</small>
          </span>
          <em>{task.progress_percent}%</em>
        </button>
      ))}
      {!tasks.length ? <p className="muted">No tasks here.</p> : null}
    </div>
  )
}

function TaskTable({ tasks }) {
  return (
    <div className="issue-table">
      <div className="issue-table__head">
        <span>Task</span>
        <span>Goal</span>
        <span>Status</span>
        <span>Progress</span>
        <span>Estimate</span>
        <span>Due</span>
      </div>
      {tasks.map((task) => (
        <button className="issue-table__row" key={task.id} onClick={() => navigate(`/tasks/${task.id}`)} type="button">
          <span>
            <strong>{task.title}</strong>
            <small>{task.type}</small>
          </span>
          <span>{task.goal_title ?? 'Inbox'}</span>
          <span>{statusLabels[task.status]}</span>
          <span>{task.progress_percent}%</span>
          <span>{minutes(task.estimate_minutes)}</span>
          <span>{task.due_at ? toDateInput(task.due_at) : '-'}</span>
        </button>
      ))}
    </div>
  )
}

export default App
