<!-- headroom:rtk-instructions -->
# RTK (Rust Token Killer) - Token-Optimized Commands

When running shell commands, **always prefix with `rtk`**. This reduces context
usage by 60-90% with zero behavior change. If rtk has no filter for a command,
it passes through unchanged — so it is always safe to use.

## Key Commands
```bash
# Git (59-80% savings)
rtk git status          rtk git diff            rtk git log

# Files & Search (60-75% savings)
rtk ls <path>           rtk read <file>         rtk grep <pattern>
rtk find <pattern>      rtk diff <file>

# Test (90-99% savings) — shows failures only
rtk pytest tests/       rtk cargo test          rtk test <cmd>

# Build & Lint (80-90% savings) — shows errors only
rtk tsc                 rtk lint                rtk cargo build
rtk prettier --check    rtk mypy                rtk ruff check

# Analysis (70-90% savings)
rtk err <cmd>           rtk log <file>          rtk json <file>
rtk summary <cmd>       rtk deps                rtk env

# GitHub (26-87% savings)
rtk gh pr view <n>      rtk gh run list         rtk gh issue list

# Infrastructure (85% savings)
rtk docker ps           rtk kubectl get         rtk docker logs <c>

# Package managers (70-90% savings)
rtk pip list            rtk pnpm install        rtk npm run <script>
```

## Rules
- In command chains, prefix each segment: `rtk git add . && rtk git commit -m "msg"`
- For debugging, use raw command without rtk prefix
- `rtk proxy <cmd>` runs command without filtering but tracks usage
<!-- /headroom:rtk-instructions -->

## Workmap Project Notes

- This repository is a local-first planner called Workmap: a single-screen,
  minimal to-do list with tags, subtasks, and a streak/activity heatmap.
  Design source of truth: `docs/superpowers/specs/2026-07-03-workmap-today-redesign-design.md`
  (read the "v3" section — it supersedes earlier versions).
- Frontend runs from `frontend/` with Vite; the whole UI is one file,
  `frontend/src/App.jsx`, rendered as a single screen (no sidebar, no
  multi-page nav).
- Backend runs from `backend/` with FastAPI + raw sqlite3 (no ORM).
- Local data is stored in SQLite at `backend/planner.sqlite3`.
- Do not reintroduce Supabase as the default storage path unless explicitly requested.
- Goals do not exist as an entity anymore — they were replaced by
  lightweight, many-to-many **tags** (`tags` + `task_tags` tables). Do not
  reintroduce `goal_id`, priority, estimate_minutes, logged_minutes, or
  progress_percent on tasks; these were intentionally removed.
- Tasks have only two statuses: `backlog` and `done`. There is no task
  detail page — checking, expanding, editing description, adding
  subtasks, and adding tags all happen inline on the row.
- AI planner should use local Ollama when available and deterministic
  fallback otherwise, and should resolve a list of tag names instead of a
  single `goal_id`.
- Mutating AI actions must be previewed before confirmation.
- New tasks must default to `backlog`.
- Verify changes with `python -m py_compile backend/api/server.py backend/db/local_store.py`, `python3 -m unittest discover backend/tests -v`, and `cd frontend && npm run lint && npm run build`.
