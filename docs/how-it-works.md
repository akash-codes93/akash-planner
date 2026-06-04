# How Akash Planner Works

## Overview

Akash Planner is a **ReAct agent** — a loop where an LLM reasons about what to do, calls tools to act, observes the result, and repeats until it can give a final answer. It's backed by Supabase (Postgres) and exposed via a FastAPI HTTP API.

```
You → FastAPI → LangGraph agent ⟲ (Thought → Action → Observation) → Answer
                                        ↕
                                    Supabase (items table)
```

---

## The ReAct Loop

ReAct = **Re**asoning + **Act**ing. There are exactly two nodes in the graph:

```
START
  │
  ▼
[agent node]  ←──────────────────┐
  │                               │
  │  LLM has tool_calls?          │
  ├── yes ──▶ [tools node] ───────┘  (loop)
  │
  └── no  ──▶ END (final answer to user)
```

### Agent node (`agent_node` in `graph.py`)
- Prepends the **system prompt** to the full message history
- Calls the LLM (Ollama local or Groq cloud)
- LLM returns either:
  - **Tool calls** → hands off to the tools node (loop continues)
  - **Plain text** → that's the final answer, loop ends

### Tools node (`ToolNode` in LangGraph)
- Executes whichever tool the LLM requested
- Appends the tool result as a `ToolMessage` to the message history
- Sends control back to the agent node

### Router (`should_continue`)
```python
def should_continue(state):
    last = state["messages"][-1]
    if last.tool_calls:
        return "tools"   # keep looping
    return END            # done
```

---

## Adding a Task

**Input:** `"Add a work task: review Casbin PR, priority 75, due tomorrow"`

```
1. POST /chat  →  FastAPI wraps message in HumanMessage

2. Agent node  →  LLM reads system prompt + tool schemas
                  Decides: call add_item(
                      title="review Casbin PR",
                      category="work",
                      item_type="task",
                      priority=75,
                      due_date="tomorrow"   ← human-friendly
                  )

3. Tools node  →  add_item() runs:
                  • resolves "tomorrow" → ISO UTC timestamp
                  • supabase.table("items").insert({...}).execute()
                  • returns "Added: 'review Casbin PR' [abc12345] — work/task p75"

4. Agent node  →  LLM sees confirmation, no more tool calls needed
                  Returns plain text answer

5. FastAPI     →  returns { steps: [action, observation, answer], answer: "..." }
```

**Key files:**
- `agent/tools.py` — `add_item()` with due date resolution + Supabase insert
- `agent/prompts.py` — tells the LLM how to infer defaults (priority ranges, effort by type)

---

## Marking a Task as Done

**Input:** `"Mark the deploy script as done"`

```
1. Agent node  →  LLM doesn't know the item's ID
                  Calls: search_items(query="deploy script")

2. Tools node  →  ILIKE search on title column in Supabase
                  Returns: "[a49d7cd1] Fix deploy script for staging"

3. Agent node  →  LLM now has the ID
                  Calls: update_item(item_id="a49d7cd1", status="done")

4. Tools node  →  update_item() runs:
                  • short ID "a49d7cd1" → fetches 500 items, finds UUID by prefix
                  • supabase.table("items")
                      .update({ status: "done", completed_at: now })
                      .eq("id", full_uuid)
                      .execute()
                  Returns: "Updated [a49d7cd1] 'Fix deploy script': status=done"

5. Agent node  →  Confirmation received, no more tool calls
                  Returns final answer to user
```

Two steps are **always required** when you don't have the ID — the agent is instructed (rule #7 in system prompt) to search first, then update. It never guesses.

---

## Memory (Multi-turn Conversations)

Every request includes a `thread_id`. LangGraph's `MemorySaver` stores the full message history — your messages, LLM responses, and all tool call results — keyed by that ID.

```python
config = {"configurable": {"thread_id": "my-session"}}
agent.invoke({"messages": [HumanMessage("Add Casbin PR")]}, config=config)
# Later, same thread_id:
agent.invoke({"messages": [HumanMessage("Actually make it high priority")]}, config=config)
# → agent knows which item from context, doesn't need to search
```

In the CLI, `thread_id = "cli-session-1"` is hardcoded so memory persists for the entire session. In the API, the caller controls `thread_id`.

---

## Tools Available (Phase 1)

| Tool | What it does |
|---|---|
| `add_item` | Insert a new item. Resolves relative dates ("tomorrow", "+3d"). Infers defaults. |
| `list_items` | List active items with filters (category, status, type). Formatted with icons + due warnings. |
| `update_item` | Update any field. Supports 8-char short IDs. Auto-sets `completed_at` on `status=done`. |
| `search_items` | ILIKE search on title. Used before update when ID is unknown. |

---

## LLM Configuration

Controlled by `LLM_PROVIDER` in `backend/.env`:

| Provider | Config | Notes |
|---|---|---|
| `ollama` | `OLLAMA_MODEL=qwen2.5:7b` | Local, unlimited, requires `brew services start ollama` |
| `groq` | `GROQ_API_KEY=...`, `GROQ_MODEL=llama-3.3-70b-versatile` | Cloud, free tier (30 req/min) |

Switch providers by changing `LLM_PROVIDER` in `.env` — no code changes needed.

---

## API Endpoints

```
POST /chat
  Body: { "message": "...", "thread_id": "..." }
  Returns: { "steps": [...], "answer": "..." }
  Each step: { "type": "action|observation|answer|thought", "content": "...",
               "tool_name": "...", "tool_input": {...} }

GET /items?category=work&status=backlog&sort_by=priority&limit=20
  Returns: { "items": [...], "count": N }
  Direct Supabase query — bypasses agent, used for fast dashboard reads.

GET /health
  Returns: { "status": "ok" }
```

---

## Running It

```bash
# CLI (interactive)
cd backend
python cli.py

# API server
cd backend
uvicorn api.server:app --reload --port 8000
```

Ollama must be running: `brew services start ollama`
