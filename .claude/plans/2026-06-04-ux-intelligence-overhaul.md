# UX + Intelligence Overhaul Plan
Date: 2026-06-04

## Problem
9 real friction points surfaced after Phase 1-3: noisy chat showing tool internals, 
token limits crashing the LLM, partial task tracking missing, abstract input not parsed,
UI feels basic, conversation memory bloated with garbage. This plan fixes all of them.

---

## Fix 1: LLM Token Problem (Root Cause)

**Root cause:** Tool docstrings are ~500 tokens each × 9 tools = 4500+ tokens. 
Add system prompt (~800) + history → exceeds Groq's 6000 TPM hard limit.

**Fix:** Trim every tool docstring to 1–2 lines. The LLM reads param names — 
it doesn't need a 30-line essay per tool. Estimated savings: 4000 tokens.

**Result:** Request drops from ~8200 → ~2000 tokens. Groq `llama-3.3-70b-versatile` 
works within limits. **No new API key needed.**

**Backup model (if Groq daily limit hits):** Mistral AI free tier.
- Sign up at console.mistral.ai → free tier, works in India, forever free.
- Model: `mistral-small-latest` — supports function calling.
- Add `LLM_PROVIDER=mistral` option in `graph.py`.
- Add `langchain-mistralai` to `requirements.txt`.

**Files:** `backend/agent/tools.py` (shorten all docstrings), 
`backend/agent/graph.py` (add mistral provider), `backend/requirements.txt`

---

## Fix 2: Chat UI — Clean Bubbles Only

**Remove:** All step cards (thought / action / observation). User doesn't want to see agent internals.

**New design:** WhatsApp/iMessage style bubbles.
- User message: right-aligned, `--accent` (#7c6af7) background, white text, rounded pill shape
- Agent message: left-aligned, `--bg-elevated` background, markdown rendered (bold/lists/code)
- Loading: 3 animated dots in agent bubble position (not "reasoning...")
- Timestamp: subtle, below each message
- Header: "akash.planner" + "New chat" button (right side)
- Empty state: greeting + 3 quick-action chips ("What should I do?", "Plan my morning", "Add a task")
- Input: full-width, rounded, send button INSIDE the input field (right side), 16px min font

**Files:** `frontend/src/components/Chat.jsx`, `frontend/src/App.css`

---

## Fix 3: Dashboard — Premium Card Redesign

**New card design:**
- Left edge: colored priority band (red 80+, amber 50-79, green <50) — 4px thick bar
- Title: bold, prominent (18px)
- Below title: `category · type · effort · cognitive load` — all small and muted
- Due date: red text if overdue/today, amber if within 3 days
- Tags: small gray pills at bottom
- Progress bar: thin bar at bottom edge of card, only when progress_percent > 0
- Quick actions (▶ Start / ✓ Done): visible on hover only, clean when resting
- Hover effect: card lifts slightly (translateY -2px), border brightens

**Filter bar:** Pill buttons. Selected = filled accent. Unselected = ghost border. 
Each category has its own accent dot color.

**Layout:** 2-column grid on desktop, 1-column on mobile.

**Files:** `frontend/src/components/Dashboard.jsx`, `frontend/src/App.css`

---

## Fix 4: Capture Form — Redesign

**New design:**
- Title input: huge (24px), bold, borderless except bottom line — Notion-style
- Category: 5 icon+label button grid (not a dropdown). Click to select, selected = filled.
  - 💼 Work · 🎯 Interview · 📚 Learning · 🌿 Personal · 🎮 Hobby
- "More details" toggle: smooth slide-down (max-height transition)
  - Item type: similar button grid (6 types with icons)
  - Priority: range slider with live colored value indicator
  - Effort: number input with quick chips (+15m, +30m, +60m)
  - Cognitive load: 3-button toggle (Low / Medium / High)
  - Due date / URL / Tags / Notes: clean labeled inputs
- Submit: full-width accent button, disabled until title filled, shows spinner on submit

**Files:** `frontend/src/components/Capture.jsx`, `frontend/src/App.css`

---

## Fix 5: Navigation Redesign

**Desktop sidebar (200px):**
- App title "akash.planner" at top with ⚡ icon
- Nav items: icon + label, active = left accent bar + slightly lighter bg
- Bottom: small "Groq / gemini" status indicator (which LLM is live)

**Mobile bottom bar:**
- 3 tabs with icons + tiny labels
- Active: accent dot underneath icon
- Background: slightly elevated, blur backdrop

**Files:** `frontend/src/App.jsx`, `frontend/src/App.css`

---

## Fix 6: Partial Task Progress

**Schema change (run in Supabase SQL Editor):**
```sql
alter table items 
add column if not exists progress_percent integer default 0 
check (progress_percent between 0 and 100);
```

**Tool change:** Add `progress_percent: int | None = None` to `update_item`.
When set + status not explicitly passed, auto-set `status = "in_progress"`.

**System prompt addition (concise):**
> When user mentions partial progress ("half done", "1/3 done", "spent 30 min on"), 
> search the item, call update_item with progress_percent (0-100) and status=in_progress.
> Confirm: "Got it — Casbin PR is 50% done. I'll remember that."

**Dashboard:** Thin `--accent` progress bar at bottom of card, visible when progress_percent > 0.

**Files:** `backend/agent/tools.py`, `backend/agent/prompts.py`, 
`frontend/src/components/Dashboard.jsx`

---

## Fix 7: Smart Item Capture (Abstract Input)

**System prompt additions:**
```
Natural language parsing rules (extract without asking):
- "30 min / X min video / watch" → item_type=video, effort_minutes=30
- "article / read / blog post"   → item_type=article, effort_minutes=20
- "leetcode / DSA / problem"     → item_type=dsa_problem, category=interview_prep, cognitive_load=high
- "important / critical / urgent"→ priority=80+
- "quick / small / 5 min"       → effort_minutes ≤ 20
- No category clue present      → infer from context or default to work/task
```

Make `category` and `item_type` inferred (still required params but LLM fills them).
Nothing changes in the tool signature — just the system prompt instruction.

**Files:** `backend/agent/prompts.py`

---

## Fix 8: Conversation Memory — Slim Down

**Current:** Saves every HumanMessage, intermediate AIMessage (with tool_calls), 
ToolMessage (observations). Grows 6–8 rows per user message. Mostly noise.

**Fix in `save_messages`:** Only persist:
1. `HumanMessage` — what the user said
2. Final `AIMessage` where `tool_calls` is empty — the actual answer

Drop: intermediate AIMessages with tool_calls, ToolMessages.

**Result:** 1 conversation turn = 2 rows. Context stays clean and useful.
`load_conversation(last_n=6)` now loads 6 actual Q&A pairs, not 6 mixed steps.

**Files:** `backend/db/memory.py`

---

## Fix 9: Goal Continuity + Archive Done Work

**New tools to add:**

`get_my_context()` — loads all user_context rows, returns as readable summary.
System prompt: "Call get_my_context on the FIRST message of each session before answering. 
This is your long-term memory — career goal, current focus, energy pattern."

`archive_done_items()` — moves all `done` items older than 2 days to `archived`.
Agent proactively offers: "You have 3 completed items from last week. Archive them?"

**Files:** `backend/agent/tools.py`, `backend/agent/prompts.py`

---

## Implementation Order

1. **Supabase SQL** — add `progress_percent` column (manual, 30 seconds)
2. **Backend** — trim docstrings + add Mistral + new tools + slim memory (one agent)
3. **Frontend** — full UI redesign: Chat + Dashboard + Capture + Nav (one agent)
4. **Test** — run CLI to verify tools work, `npm run build` to verify frontend

---

## Verification
- "I've done half the Casbin PR" → update_item(progress_percent=50, status=in_progress) ✓
- "watch this 30 min Go video: url" → add_item infers video/30m/learning ✓
- Conversations table: only 2 rows per exchange (not 6-8) ✓
- Chat: no step cards, only clean bubbles ✓
- Dashboard: progress bars on in-progress items ✓
- "Archive my done tasks" → archive_done_items() runs ✓
- Token test: single request < 3000 tokens with trimmed docstrings ✓
