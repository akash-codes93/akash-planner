# Akash Planner — ReAct Agent for Personal Productivity

## What is this project?

A ReAct (Reasoning + Acting) agent that manages Akash's learning backlog, work tasks, interview prep, and personal growth. It doesn't just store tasks — it reasons about what to do next based on deadlines, energy levels, cognitive load, and career goals.

This is both a learning project (understand how ReAct agents work) and a practical tool (actually use it daily from phone/laptop).

## The core user experience

Akash opens a chat (web or mobile), types something like:
- "It's 10 PM, I'm tired. What should I do?"
- "Add a work task: review Casbin PR, high priority, due tomorrow"
- "I've decided to start interviewing. Reprioritize everything."
- "Plan my morning — I have 2 hours before standup"

The agent reasons step-by-step (Thought → Action → Observation → loop), calls tools that read/write to a Supabase database, and gives an opinionated answer.

## Architecture

```
Frontend (React + Vite, Netlify)         ← Phase 3
    │
    │ REST API (POST /chat, GET /items)
    ▼
Backend (Python FastAPI, Render)         ← Phase 1-2
    │
    ├── LangGraph ReAct Agent
    │     │
    │     ├── agent node → calls LLM
    │     │     │
    │     │     ├── has tool_calls? → tools node → back to agent (THE LOOP)
    │     │     └── no tool_calls? → END (final answer)
    │     │
    │     └── tools node → executes tool functions against Supabase
    │
    ├── Supabase Client (supabase-py)
    │
    └── LLM Provider (switchable via env var)
          ├── Ollama (local dev) — qwen2.5:7b
          └── Groq (deployed) — llama-3.3-70b-versatile (free tier)

Database (Supabase / Postgres)
    ├── items          — tasks, videos, articles, DSA problems, notes
    ├── conversations  — chat history grouped by thread_id
    └── user_context   — career goals, energy patterns, work hours
```

## Tech stack (all free)

| Layer | Tool | Free tier limits |
|---|---|---|
| Backend | Python 3.11+ / FastAPI | — |
| Agent framework | LangGraph (pip) | Open source |
| Database | Supabase | 500MB, 50K rows |
| LLM (local) | Ollama + qwen2.5:7b | Unlimited, local |
| LLM (cloud) | Groq + llama-3.3-70b | 30 req/min, free |
| Frontend | React + Vite | — |
| Frontend hosting | Netlify | 100GB bandwidth/mo |
| Backend hosting | Render | 750 hrs/mo |

## Supabase — ALREADY SET UP

Project exists. Schema applied. Tables:

**`items`** — single table for ALL item types. Key columns:
- `id` uuid PK
- `title` text, `description` text
- `category` text: 'work' | 'interview_prep' | 'learning' | 'personal' | 'hobby'
- `item_type` text: 'task' | 'article' | 'video' | 'course' | 'dsa_problem' | 'note' | 'idea'
- `tags` text[]
- `priority` int 0-100 (NOT enum — agent adjusts dynamically)
- `effort_minutes` int, `cognitive_load` text (low/medium/high)
- `due_date` timestamptz (nullable)
- `status` text: 'backlog' | 'today' | 'in_progress' | 'done' | 'archived'
- `completed_at` timestamptz
- `url` text, `source` text, `notes` text
- `created_at`, `updated_at` (auto-trigger)

**`conversations`** — chat memory by thread:
- `thread_id` text, `role` text (user/assistant/tool), `content` text
- `tool_calls` jsonb, `tool_call_id` text, `tool_name` text

**`user_context`** — key-value long-term memory:
- `key` text unique, `value` jsonb
- Seeded with: career_goal, work_hours (10:00-19:00 IST), energy_pattern (morning=high, evening=low), current_focus, categories_active

10 seed items exist. RLS disabled (Phase 1). Indexes on status+category, priority desc, due_date, thread+created_at, title trigram.

## Target project structure

```
akash-planner/
├── CLAUDE.md                        ← this file
├── .claude/
│   └── plans/
│       ├── phase1-foundation.md     ← current phase
│       ├── phase2-intelligence.md
│       ├── phase3-frontend.md
│       └── phase4-deploy.md
├── backend/
│   ├── agent/
│   │   ├── __init__.py
│   │   ├── graph.py                 ← LangGraph state graph (the ReAct loop)
│   │   ├── tools.py                 ← @tool functions that query Supabase
│   │   ├── scoring.py               ← Priority scoring algorithm (Phase 2)
│   │   └── prompts.py               ← System prompt
│   ├── api/
│   │   ├── __init__.py
│   │   ├── server.py                ← FastAPI app
│   │   └── routes.py                ← /chat, /items endpoints
│   ├── db/
│   │   ├── __init__.py
│   │   └── supabase_client.py       ← Supabase connection singleton
│   ├── cli.py                       ← CLI for testing the agent
│   ├── requirements.txt
│   ├── .env.example
│   └── .env                         ← NOT committed
├── frontend/                        ← Phase 3
└── supabase/
    └── migrations/
        └── 001_initial_schema.sql   ← already applied
```

## Environment variables (backend/.env)

```
SUPABASE_URL=<from Supabase dashboard → Settings → API → Project URL>
SUPABASE_KEY=<from Supabase dashboard → Settings → API → anon public key>
LLM_PROVIDER=ollama
OLLAMA_MODEL=qwen2.5:7b
GROQ_API_KEY=<only when LLM_PROVIDER=groq, get from console.groq.com>
GROQ_MODEL=llama-3.3-70b-versatile
```

## Coding conventions

- Python 3.11+ — use `X | None` not `Optional[X]` from typing
- Type hints on all function signatures
- Every @tool function needs a detailed docstring — the LLM reads this to decide when/how to call the tool
- Use `supabase-py` client for all DB operations, not raw SQL from Python
- Module-level docstring on every file explaining what it does
- Imports order: stdlib → third-party → local, blank line between groups
- Error messages must be human-readable (the LLM reads tool output to reason about next steps)
- FastAPI endpoints use Pydantic models for request/response

## How the ReAct loop works (reference for agent implementation)

```python
# This is the entire agent logic:

graph.add_node("agent", agent_node)      # calls LLM
graph.add_node("tools", tool_node)        # executes tools
graph.add_edge(START, "agent")            # entry
graph.add_conditional_edges("agent", should_continue)  # branch
graph.add_edge("tools", "agent")          # ← THE LOOP

def should_continue(state):
    last = state["messages"][-1]
    if last.tool_calls:
        return "tools"   # keep looping
    return END            # done
```

The LLM gets: system prompt + conversation history + tool definitions.
It returns: either tool_calls (→ loop continues) or plain text (→ done).

## Phases overview

- **Phase 1 (Foundation):** Supabase client + 4 tools (add, list, update, search) + LangGraph agent + CLI + FastAPI server
- **Phase 2 (Intelligence):** suggest_next + plan_day + reprioritize tools + scoring algorithm + conversation memory in Supabase
- **Phase 3 (Frontend):** React chat UI + dashboard + quick capture, mobile responsive
- **Phase 4 (Deploy):** Render backend + Groq LLM + Supabase Auth + Netlify frontend

## Current status

- [x] Supabase project created, schema applied, seed data loaded
- [ ] Phase 1 ← START HERE (see .claude/plans/phase1-foundation.md)
