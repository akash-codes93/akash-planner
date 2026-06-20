# Workmap

Local-first planner for goals, tasks, due dates, focus sessions, and AI-assisted planning.

## Run Locally

```bash
cd backend
python -m uvicorn api.server:app --host 127.0.0.1 --port 8000
```

```bash
cd frontend
npm run dev -- --host 127.0.0.1 --port 5173
```

Open `http://127.0.0.1:5173/`.

## AI Planner

Workmap uses local Ollama (`qwen2.5:7b` by default) when available and falls back to deterministic parsing.

Example commands:

```text
Create a task under Switch job preparation to study payment system design
What should I study next?
Summarize my planner
What can you do?
```

Mutating AI actions are shown as drafts before confirmation.

## Documentation

See [docs/how-it-works.md](docs/how-it-works.md).
