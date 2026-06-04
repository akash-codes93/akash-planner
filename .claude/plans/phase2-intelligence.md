# Phase 2: Intelligence — Smart Tools + Scoring + Memory

## Goal
Make the agent actually intelligent. It should recommend what to work on next based on deadlines, energy, cognitive load, and career goals. Conversations persist to Supabase so memory survives server restarts.

## Prerequisites
- Phase 1 complete: CLI and FastAPI work, 4 basic tools operational
- Supabase has items, conversations, user_context tables with data

## Steps

### Step 1: Priority scoring engine
Create `backend/agent/scoring.py`:

Implement `score_item(item: dict, context: dict) -> float` that computes a composite score:

```
score = (
    base_priority                          # item's stored priority (0-100)
    + deadline_urgency(due_date)           # 0 if no deadline, exponential as it approaches
                                           # +30 if due today, +20 if due tomorrow, +10 if due in 3 days
                                           # +50 if overdue
    + career_alignment(category, goals)    # +10 if category matches current_focus
    - cognitive_mismatch(load, energy)     # -20 if high-load + low-energy, -10 if high-load + medium-energy
    - time_overflow(effort, available)     # -15 if effort_minutes > available_minutes
    + recency_bonus(created_at)            # +5 if created in last 24 hours (fresh items get a nudge)
)
```

`context` dict comes from user_context table + runtime info (current time → derive energy from energy_pattern, available_minutes from user input).

Also implement `rank_items(items: list[dict], context: dict) -> list[dict]` that scores and sorts all items.

TEST: write a small test that creates mock items with different priorities/deadlines/loads and verifies the scoring produces the expected ranking.

### Step 2: suggest_next tool
Add to `backend/agent/tools.py`:

**suggest_next(available_minutes: int, energy_level: str, context: str)**
- energy_level: 'high', 'medium', 'low' (if not provided, infer from current time + user_context.energy_pattern)
- Query all non-done/archived items from Supabase
- Load user_context (career_goal, current_focus)
- Build scoring context dict with energy, available time, goals
- Run rank_items() from scoring.py
- Return top 3-5 items with scores and WHY each ranks where it does
- Format should explain: "P92 — Casbin PR review [due tomorrow, +30 deadline boost, but high cognitive load with your low energy, -20]"

This is the most important tool. The agent calls this, reads the ranked results with explanations, and then REASONS about them to give a final recommendation. The reasoning (the Thought step) is where it might override the scoring: "Scoring says DSA, but you've done 2 hours of DSA today — try the Go video instead."

### Step 3: plan_day tool
Add to `backend/agent/tools.py`:

**plan_day(date: str, total_hours: float, energy_profile: str)**
- date: defaults to "today"
- total_hours: how many hours available
- energy_profile: "standard" uses the stored pattern (high morning → low evening)
- Logic:
  1. Query all items with status in (backlog, today, in_progress) sorted by priority
  2. Load user_context for work_hours and energy_pattern
  3. Divide the day into blocks based on energy: morning (high energy) → high cognitive load tasks, afternoon (medium) → medium tasks, evening (low) → videos/articles
  4. Fit items into blocks respecting effort_minutes estimates
  5. Include break slots (15 min after every 90 min of work)
- Return a formatted time-blocked plan

### Step 4: reprioritize tool
Add to `backend/agent/tools.py`:

**reprioritize(trigger: str)**
- trigger: natural language like "I'm starting to interview" or "big deadline moved to Friday"
- Logic:
  1. Load all non-done items
  2. Based on trigger, apply bulk priority adjustments:
     - "interviewing" → boost interview_prep category +15, slightly reduce hobby -10
     - "deadline" → boost related work items +20
     - Generic: the LLM reasons about what to adjust (this tool just loads data, the agent decides)
  3. Update priorities in Supabase
  4. Return summary of what changed: "Adjusted 8 items: interview_prep avg priority 55→70, hobby avg 40→30"

### Step 5: get_stats tool
Add to `backend/agent/tools.py`:

**get_stats(period: str)**
- period: "today", "week", "month"
- Query completed items in the period
- Return: items completed (by category), total effort logged, current backlog size by category, streak info
- This feeds the agent's "you should take a break" or "you've been ignoring interview prep" reasoning

### Step 6: Supabase conversation memory
Replace the in-memory MemorySaver with Supabase-backed persistence.

Create `backend/db/memory.py`:
- Implement a custom checkpointer OR simpler approach:
  - After each agent run, save the full message history to the `conversations` table
  - Before each agent run, load previous messages for that thread_id
  - This is simpler than implementing LangGraph's BaseCheckpointSaver and works fine for a single-user app

Modify `backend/agent/graph.py`:
- Before invoking the agent, load conversation history from Supabase for the thread_id
- After the agent finishes, save new messages to Supabase
- Keep MemorySaver for within-session (fast), use Supabase for cross-session (persistent)

TEST: Start CLI, add a task, quit, restart CLI with SAME thread_id, ask "what did I just add?" — it should remember.

### Step 7: Update user_context from conversation
Add to `backend/agent/tools.py`:

**update_my_context(key: str, value: str)**
- Allows the agent to update user_context when it detects a life change
- When user says "I'm interviewing now", the agent should:
  1. Call reprioritize(trigger="interviewing")
  2. Call update_my_context(key="current_focus", value="Interview preparation + current work")
- This persists the change so future sessions know about it too

Update ALL_TOOLS to include: suggest_next, plan_day, reprioritize, get_stats, update_my_context

### Step 8: Enhance system prompt
Update `backend/agent/prompts.py`:
- Add instructions for the new tools
- Tell the agent WHEN to use suggest_next vs plan_day (suggest = quick "what next?", plan = structured day/morning plan)
- Tell it to call get_stats before making "you should take a break" suggestions
- Tell it to proactively call update_my_context when it detects context changes

## Verification checklist
- [ ] "What should I do next? I have 30 minutes and low energy" → calls suggest_next, reasons about results
- [ ] "Plan my morning, I have 3 hours" → calls plan_day, returns time blocks
- [ ] "I'm going to start interviewing" → calls reprioritize + update_my_context
- [ ] "How productive was I this week?" → calls get_stats, gives analysis
- [ ] Quit CLI, restart, agent remembers previous conversation
- [ ] Scoring correctly boosts overdue items and penalizes cognitive mismatches
