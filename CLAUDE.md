# Workmap Developer Notes

Workmap is a local-first personal planner: a minimal, single-screen to-do
list with tags, subtasks, and a streak/activity heatmap. Design intent lives
in `docs/superpowers/specs/2026-07-03-workmap-today-redesign-design.md`
(read the "v3" section first — it supersedes v1/v2 for data model and UI).

## Current Stack

- Frontend: Vite + React (single file: `frontend/src/App.jsx`)
- Backend: FastAPI + raw sqlite3 (no ORM)
- Storage: SQLite at `backend/planner.sqlite3`
- AI: Ollama `qwen2.5:7b` by default, deterministic fallback

## Local Commands

Backend:

```bash
cd backend
python -m uvicorn api.server:app --host 127.0.0.1 --port 8000
```

Frontend:

```bash
cd frontend
npm run dev -- --host 127.0.0.1 --port 5173
```

Verification:

```bash
python -m py_compile backend/api/server.py backend/db/local_store.py
python3 -m unittest discover backend/tests -v
cd frontend && npm run lint && npm run build
```

## Product Model (v3)

The app is one screen: capture bar, streak/heatmap strip, tag filter row,
flat task table. No sidebar, no separate pages (Today/Board/Goals/Planning/
AI Planner pages were removed; the `/chat` and `/api/ai/*` endpoints still
exist but are unlinked from the UI).

- **Tasks**: single-line `title`, optional short `description`, optional
  `due_at`, `status` is `backlog` or `done` only. No priority, estimate,
  logged_minutes, or progress_percent — those fields were removed entirely.
- **Subtasks**: one level of nesting via `parent_task_id` on the same
  `tasks` table. Completing the last open subtask auto-completes the
  parent (cascade in `complete_task`).
- **Tags**: goals were replaced by lightweight tags. A `tags` table
  (`id`, `name`) plus a `task_tags` join table give tasks a many-to-many
  relationship. Tags are pure filter/metadata — no dedicated goals/tags
  page, no progress rollups. Subtasks inherit their parent's tags for
  filtering purposes.
- **Activity/streak**: `activity_log` (one row per day) and
  `streak_freezes` (one freeze token per rolling 7-day window) drive the
  heatmap and streak count, computed on read in `get_activity()`.
- **No task detail page**: every interaction (check, expand, edit
  description, add subtask, add tag) happens inline on the row.

## AI Planner Rules

- AI may draft actions, but mutating actions require confirmation.
- AI-created tasks must default to `backlog`.
- AI should refine task title/description and resolve `tags` (a list of
  tag names, matched against existing tags where possible) instead of a
  single `goal_id` — goals/`goal_id` no longer exist in the model.
- If Ollama is unavailable or weak, deterministic fallback must still
  produce a usable draft.

## Important Files

- `backend/db/local_store.py`: SQLite schema, repositories (tasks, tags,
  activity/streak), AI draft normalization.
- `backend/api/server.py`: FastAPI routes.
- `frontend/src/App.jsx`: the entire Workmap UI (single-screen, no router
  beyond a single view).
- `frontend/src/App.css`: visual system — soft glass surfaces, one accent
  color (green, `#16a34a` family) for checkboxes/tag-filter/heatmap, red
  for the streak flame only.
- `docs/how-it-works.md`: architecture documentation (predates v3 — data
  model section is stale, see the v3 spec instead).
- `docs/superpowers/specs/2026-07-03-workmap-today-redesign-design.md`:
  source of truth for the current UI/data-model design.
