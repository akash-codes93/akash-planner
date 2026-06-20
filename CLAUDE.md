# Workmap Developer Notes

Workmap is a local-first personal planner.

## Current Stack

- Frontend: Vite + React
- Backend: FastAPI
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
cd frontend && npm run lint && npm run build
```

## Product Model

The app is organized around:

- Goals
- Tasks
- Due dates
- Progress
- Focus sessions
- AI action drafts

Tasks may drag across days, so planning is not day-only. Use due dates, stale signals, and progress history.

## AI Planner Rules

- AI may draft actions, but mutating actions require confirmation.
- AI-created tasks must default to `backlog`.
- AI should refine task title/description/priority/estimate/tags instead of copying raw input.
- AI should resolve `goal_id` from existing local goals when confidence is high.
- If Ollama is unavailable or weak, deterministic fallback must still produce a usable draft.

## Important Files

- `backend/db/local_store.py`: SQLite schema, repositories, AI draft normalization.
- `backend/api/server.py`: FastAPI routes.
- `frontend/src/App.jsx`: main Workmap UI.
- `frontend/src/App.css`: visual system.
- `docs/how-it-works.md`: architecture documentation.
