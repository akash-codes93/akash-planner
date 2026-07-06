# Workmap

Local-first planner — tasks, tags, subtasks, streak heatmap, AI-assisted planning.
Ships as a standalone Electron desktop app.

## Quick Start (Electron Desktop App)

```bash
# One-time setup
pip install pyinstaller
cd electron && npm install

# Full build + launch
npm run electron
```

Produces the Workmap window on your desktop with backend + frontend bundled.

## Development (Web — hot reload)

```bash
# Terminal 1: Backend
cd backend
uvicorn api.server:app --reload

# Terminal 2: Frontend
cd frontend
npm run dev
```

Open `http://localhost:5173`.

## Production Build (DMG)

```bash
npm run electron:build
```

Output: `electron/release/Workmap-1.0.0-arm64.dmg`

Open the DMG, drag `Workmap.app` to `/Applications`. Launch from Applications.
The app is unsigned — macOS may require right-click → Open on first launch.

## Project Layout

```
akash_planner/
├── frontend/              React 19 + Vite (single-screen UI)
│   ├── src/App.jsx        Entire UI in one file
│   ├── src/App.css        All styles
│   └── dist/              Build output (consumed by Electron)
├── backend/               FastAPI + sqlite3
│   ├── api/server.py      API routes
│   ├── db/local_store.py  SQLite operations + AI logic
│   ├── agent/             Ollama / LangGraph agent
│   ├── planner.sqlite3    Local data
│   └── build.py           PyInstaller script
├── electron/              Electron shell
│   ├── main.js            Main process (spawn backend, serve frontend)
│   ├── electron-builder.yml
│   ├── icon.png           512×512 app icon
│   └── release/           DMG output
└── package.json           Workspace convenience scripts
```

## How It Works

| Layer | Technology | Role |
|---|---|---|
| Window | Electron (BrowserWindow) | Native Mac window with sparkle icon |
| Frontend | React 19 + Vite | Served via Node static server on port 5174 |
| Backend | FastAPI + uvicorn | PyInstaller binary running on port 8000 |
| Storage | SQLite (raw, no ORM) | `backend/planner.sqlite3` |
| AI | Ollama + deterministic fallback | Planner chat, task suggestions |

`Workmap.app` spins up the backend binary + frontend server as child processes, then opens the window. Quitting the app kills both.

## AI Planner

Uses local Ollama (`qwen2.5:7b` by default) when available, falls back to deterministic parsing.

Example commands:

```text
Create a task under interview prep to study system design
What should I study next?
Summarize my planner
What can you do?
```

Mutating AI actions are shown as drafts before confirmation.

## Documentation

See [docs/how-it-works.md](docs/how-it-works.md).
