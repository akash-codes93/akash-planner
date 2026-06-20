# Workmap Architecture

Workmap is a local-first personal planning app for goals, tasks, due dates, focus sessions, and AI-assisted task drafting.

## Runtime

- Frontend: Vite + React
- Backend: FastAPI
- Database: local SQLite at `backend/planner.sqlite3`
- AI: local Ollama via `qwen2.5:7b` by default, with deterministic fallback

## Local Run

Terminal 1:

```bash
cd backend
python -m uvicorn api.server:app --host 127.0.0.1 --port 8000
```

Terminal 2:

```bash
cd frontend
npm run dev -- --host 127.0.0.1 --port 5173
```

Open:

```text
http://127.0.0.1:5173/
```

## Data Model

`goals`
- title
- description
- status
- priority
- progress_percent

`tasks`
- goal_id
- title
- description
- status: `backlog`, `next`, `doing`, `blocked`, `done`
- type
- priority
- estimate_minutes
- logged_minutes
- progress_percent
- due_at
- planned_start_at
- last_worked_at
- completed_at
- archived_at
- tags_json

`focus_sessions`
- task_id
- started_at
- ended_at
- duration_minutes
- progress_delta
- summary

`llm_action_drafts`
- action_type
- input_text
- proposed_payload_json
- status

## Pages

- Dashboard: global overview, goals, suggested tasks, recent tasks
- Planning: overdue, due soon, stale/dragged, no due date
- Goal: editable goal settings, board/list/timeline task views
- Task: editable task metadata, due date, estimate, priority, progress, focus notes
- AI Planner: command input, preview, confirm

## AI Planner Behavior

The AI planner creates drafts before mutating data.

Non-mutating commands render immediately:
- `What should I study next?`
- `Summarize my planner`
- `What can you do?`

Mutating commands require confirmation:
- create goal
- create task
- complete current task

Task drafting uses:
1. Local Ollama structured parsing when available.
2. Validation and normalization against local goals.
3. Deterministic fallback when Ollama is unavailable or returns weak JSON.

New AI-created tasks always start in `backlog`.

The AI draft payload should prefill:
- refined title
- description
- goal_id when confidently matched
- type
- priority
- estimate_minutes
- due_at
- tags

## Local Data Reset

Use `Clear local data` in the sidebar. This removes all local goals, tasks, sessions, events, and AI drafts. After clearing, seed data stays disabled so the workspace remains empty.
