# Phase 1: Foundation — Supabase Client + LangGraph Agent + CLI + FastAPI

## Goal
Build a working ReAct agent that talks to Supabase, testable via CLI and HTTP API.
By the end: `python cli.py` lets you chat with the agent, and it reads/writes items in Supabase.

## Prerequisites
- Supabase project is live with schema applied (items, conversations, user_context tables)
- Ollama installed and running (`ollama serve`), model pulled (`ollama pull qwen2.5:7b`)
- SUPABASE_URL and SUPABASE_KEY available from Supabase dashboard → Settings → API

## Steps

### Step 1: Project scaffolding
Create the directory structure and configuration files:
- `backend/requirements.txt` with: fastapi>=0.115.0, uvicorn>=0.30.0, langgraph>=0.4.0, langchain-core>=0.3.0, langchain-ollama>=0.3.0, langchain-groq>=0.3.0, supabase>=2.0.0, python-dotenv>=1.0.0
- `backend/.env.example` with all env vars documented (SUPABASE_URL, SUPABASE_KEY, LLM_PROVIDER, OLLAMA_MODEL, GROQ_API_KEY, GROQ_MODEL)
- `backend/.env` copied from example — ASK the user for their Supabase URL and anon key, then write the .env file
- `backend/agent/__init__.py`, `backend/db/__init__.py`, `backend/api/__init__.py` (empty init files)
- `.gitignore` with: .env, __pycache__/, *.pyc, .venv/
- Install dependencies: `cd backend && pip install -r requirements.txt`

### Step 2: Supabase client
Create `backend/db/supabase_client.py`:
- Singleton pattern: `get_supabase()` returns a cached `supabase.Client`
- Reads SUPABASE_URL and SUPABASE_KEY from environment
- Uses `python-dotenv` to load .env
- TEST: write a quick script that calls `get_supabase().table("items").select("*").limit(1).execute()` and prints the result. Verify it returns seed data.

### Step 3: System prompt
Create `backend/agent/prompts.py`:
- SYSTEM_PROMPT constant string
- The agent is "Akash's personal planner agent"
- Instructions: always use tools to check data (never guess), infer sensible defaults when adding items (priority ranges by category, effort by type, cognitive load by type), consider time/energy/deadlines when suggesting, be direct and opinionated ("Do X" not "you could do X or Y"), keep responses concise
- List the categories and item types the agent knows about
- Tell it to proactively suggest reprioritization when context changes

### Step 4: Agent tools
Create `backend/agent/tools.py`:
- Import `@tool` from `langchain_core.tools`
- Import `get_supabase` from `db.supabase_client`

Implement these 4 tools:

**add_item(title, category, item_type, priority, effort_minutes, cognitive_load, due_date, url, tags, notes)**
- All params except title/category/item_type have defaults
- Resolve relative due dates: "tomorrow" → now + 1 day, "+3days" → now + 3 days, else treat as ISO string
- Set source="agent"
- Insert via supabase-py, return confirmation with short ID

**list_items(category, status, item_type, limit, sort_by)**
- All params optional. Default: exclude done/archived, sort by priority desc, limit 10
- Format output with status icons (○ backlog, ◉ today, ▶ in_progress, ✓ done)
- Show priority, title, category/type, effort, cognitive load, due date warning (OVERDUE/DUE TODAY/due in Xd)
- Include short ID (first 8 chars of uuid) so user/agent can reference items

**update_item(item_id, status, priority, title, notes, due_date, effort_minutes, cognitive_load)**
- Support short IDs: if item_id < 36 chars, query with ILIKE to find full UUID
- If status set to "done", auto-set completed_at
- Return confirmation with what changed

**search_items(query)**
- ILIKE search on title column
- Exclude archived items
- Sort by priority desc, limit 10

Export `ALL_TOOLS = [add_item, list_items, update_item, search_items]`

### Step 5: LangGraph ReAct agent
Create `backend/agent/graph.py`:
- `_get_llm()` function that checks LLM_PROVIDER env var:
  - "ollama" → `ChatOllama(model=OLLAMA_MODEL, temperature=0)`
  - "groq" → `ChatGroq(model=GROQ_MODEL, api_key=GROQ_API_KEY, temperature=0)`
- `build_agent()` function that:
  1. Creates LLM via `_get_llm()` and calls `.bind_tools(ALL_TOOLS)`
  2. Defines `agent_node(state)` — prepends SystemMessage with SYSTEM_PROMPT, calls LLM, returns response
  3. Creates `ToolNode(ALL_TOOLS)` for the tools node
  4. Defines `should_continue(state)` — checks if last message has tool_calls → return "tools", else → return END
  5. Builds StateGraph(MessagesState) with two nodes ("agent", "tools"), edges: START→agent, agent→conditional(should_continue), tools→agent
  6. Compiles with MemorySaver checkpointer
  7. Returns compiled graph

### Step 6: CLI interface
Create `backend/cli.py`:
- Import build_agent from agent.graph
- `stream_agent(agent, user_input, config)` function that:
  - Calls `agent.stream({"messages": [HumanMessage(content=user_input)]}, config=config)`
  - Iterates over events, prints each step with ANSI colors:
    - Agent node + AIMessage with tool_calls → print THOUGHT (if text content) + ACTION (tool name + args)
    - Tools node + ToolMessage → print OBSERVATION (tool result)
    - Agent node + AIMessage without tool_calls → print FINAL ANSWER
- Main loop: input → stream_agent → repeat. Config has `thread_id: "cli-session-1"` for memory.
- Support "quit" to exit

TEST the CLI with:
1. "What's in my backlog?" — should call list_items, show seed data
2. "Add a work task: investigate go-common secret scanning false positives, priority 75, due tomorrow" — should call add_item
3. "Search for kafka" — should call search_items
4. "Mark the deploy script as done" — should first search/list to find it, then call update_item (multi-step!)

### Step 7: FastAPI server
Create `backend/api/server.py`:
- FastAPI app with CORS middleware (allow all origins for Phase 1)
- POST `/chat` — accepts `{"message": str, "thread_id": str}`, runs the agent, returns `{"steps": [...], "answer": str}`
  - Each step is `{"type": "thought"|"action"|"observation"|"answer", "content": str, "tool_name": str|null, "tool_input": dict|null}`
  - This structured response lets the frontend render the ReAct loop visually later
- GET `/items` — direct Supabase query with optional query params: category, status, sort_by, limit
  - This bypasses the agent for fast dashboard reads
- GET `/health` — returns `{"status": "ok"}`

Create `backend/api/routes.py` if you want to separate route logic from app setup.

The server.py should be runnable with: `cd backend && uvicorn api.server:app --reload --port 8000`

TEST the API with:
```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "What tasks do I have?", "thread_id": "test-1"}'
```

## Verification checklist
After all steps, verify:
- [ ] `python cli.py` starts without errors
- [ ] Asking "what's in my backlog?" returns the 10 seed items from Supabase
- [ ] Adding an item via chat creates a row in Supabase (check Table Editor)
- [ ] Multi-step queries work: "mark the deploy script as done" triggers search → update
- [ ] `uvicorn api.server:app --reload` starts, POST /chat returns structured response
- [ ] Memory works: in the same CLI session, the agent remembers what you said earlier
