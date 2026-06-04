"""
LangChain @tool functions for the akash-planner ReAct agent.

Each tool wraps a Supabase operation. The LLM reads the docstrings to
decide when and how to call each tool, so docstrings must be detailed
and describe every parameter precisely.

Tools exported:
    add_item           — insert a new item into the backlog
    list_items         — list items with filters and formatted output
    update_item        — update fields on an existing item
    search_items       — full-text search on item titles
    suggest_next       — score + rank items for the current moment (Phase 2)
    plan_day           — build a time-blocked day plan (Phase 2)
    reprioritize       — bulk-adjust priorities based on a life-change trigger (Phase 2)
    get_stats          — productivity stats for today/week/month (Phase 2)
    update_my_context  — update user_context key-value store (Phase 2)

ALL_TOOLS is the list passed to LLM.bind_tools() and ToolNode.
"""

import json
import os
from datetime import datetime, timedelta, timezone

from langchain_core.tools import tool

from agent.scoring import rank_items
from db.supabase_client import get_supabase

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_STATUS_ICONS: dict[str, str] = {
    "backlog": "○",
    "today": "◉",
    "in_progress": "▶",
    "done": "✓",
    "archived": "⊘",
}


def _resolve_due_date(due_date: str | None) -> str | None:
    """Resolve human-friendly due date strings to ISO-8601 UTC strings.

    Supports:
        "tomorrow"      → now + 1 day
        "+Nd" / "+Ndays"→ now + N days (e.g. "+3d", "+3days")
        Any other value → returned as-is (assumed ISO-8601)
        None            → None
    """
    if due_date is None:
        return None
    now = datetime.now(tz=timezone.utc)
    lower = due_date.strip().lower()
    if lower == "tomorrow":
        return (now + timedelta(days=1)).isoformat()
    if lower.startswith("+"):
        digits = lower.lstrip("+").rstrip("days").rstrip("d")
        try:
            return (now + timedelta(days=int(digits))).isoformat()
        except ValueError:
            pass
    return due_date


def _due_warning(due_date_str: str | None) -> str:
    """Return a human-readable due date warning string."""
    if not due_date_str:
        return ""
    try:
        # Parse ISO string; supabase returns timezone-aware strings
        dt = datetime.fromisoformat(due_date_str.replace("Z", "+00:00"))
        now = datetime.now(tz=timezone.utc)
        delta = (dt.date() - now.date()).days
        if delta < 0:
            return " [OVERDUE]"
        if delta == 0:
            return " [DUE TODAY]"
        return f" [due in {delta}d]"
    except Exception:
        return f" [due: {due_date_str[:10]}]"


def _format_item(item: dict) -> str:
    """Format a single item row for display in tool output."""
    icon = _STATUS_ICONS.get(item.get("status", "backlog"), "?")
    short_id = (item.get("id") or "")[:8]
    priority = item.get("priority", 0)
    title = item.get("title", "(no title)")
    category = item.get("category", "")
    item_type = item.get("item_type", "")
    effort = item.get("effort_minutes")
    cog = item.get("cognitive_load", "")
    due_warning = _due_warning(item.get("due_date"))

    effort_str = f" {effort}m" if effort else ""
    cog_str = f" {cog}" if cog else ""

    return (
        f"{icon} [{short_id}] p{priority} {title}"
        f"  ({category}/{item_type}){effort_str}{cog_str}{due_warning}"
    )


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@tool
def add_item(
    title: str,
    category: str,
    item_type: str,
    priority: int = 50,
    effort_minutes: int = 30,
    cognitive_load: str = "medium",
    due_date: str | None = None,
    url: str | None = None,
    tags: list[str] | None = None,
    notes: str | None = None,
    description: str | None = None,
) -> str:
    """Add a new item to Akash's planner backlog.

    Use this tool whenever the user wants to capture something new — a task,
    article to read, video to watch, DSA problem, idea, note, etc.

    Args:
        title:          Short, descriptive name for the item. Required.
        category:       One of: work, interview_prep, learning, personal, hobby. Required.
        item_type:      One of: task, article, video, course, dsa_problem, note, idea. Required.
        priority:       Integer 0–100. Default 50. Use 70–89 for high, 50–69 medium,
                        30–49 low, 90+ for blocking/urgent.
        effort_minutes: Estimated time to complete in minutes. Default 30.
        cognitive_load: "low", "medium", or "high". Default "medium".
                        dsa_problem/course → high; article/video → low; task → medium.
        due_date:       Optional deadline. Accepts: "tomorrow", "+3d", "+3days",
                        or any ISO-8601 date string. Omit if no deadline.
        url:            Optional link (article URL, LeetCode problem, YouTube link, etc.)
        tags:           Optional list of string tags for filtering. e.g. ["golang", "kafka"]
        notes:          Optional additional context or details about the item.
        description:    Optional longer description. Use notes for quick context,
                        description for structured details.

    Returns:
        Confirmation string with the short ID of the created item, e.g.:
        "Added: 'Review Casbin PR' [abc12345] — work/task p75 30m medium"
    """
    db = get_supabase()
    resolved_due = _resolve_due_date(due_date)

    payload: dict = {
        "title": title,
        "category": category,
        "item_type": item_type,
        "priority": priority,
        "effort_minutes": effort_minutes,
        "cognitive_load": cognitive_load,
        "source": "agent",
        "status": "backlog",
    }
    if resolved_due:
        payload["due_date"] = resolved_due
    if url:
        payload["url"] = url
    if tags:
        payload["tags"] = tags
    if notes:
        payload["notes"] = notes
    if description:
        payload["description"] = description

    try:
        result = db.table("items").insert(payload).execute()
        if not result.data:
            return "Error: insert returned no data. Check Supabase connection and RLS settings."
        created = result.data[0]
        short_id = (created.get("id") or "")[:8]
        due_str = _due_warning(created.get("due_date"))
        return (
            f"Added: '{title}' [{short_id}] — {category}/{item_type} "
            f"p{priority} {effort_minutes}m {cognitive_load}{due_str}"
        )
    except Exception as e:
        return f"Error adding item: {e}"


@tool
def list_items(
    category: str | None = None,
    status: str | None = None,
    item_type: str | None = None,
    limit: int = 10,
    sort_by: str = "priority",
) -> str:
    """List items from Akash's planner with optional filters.

    Use this tool to answer questions like:
    - "What's in my backlog?"
    - "Show me my work tasks"
    - "What DSA problems do I have?"
    - "What's due today?"

    By default, excludes done and archived items (shows only active items).
    Pass status="done" explicitly to see completed items.

    Args:
        category:  Filter by category: work, interview_prep, learning, personal, hobby.
                   Omit to show all categories.
        status:    Filter by status: backlog, today, in_progress, done, archived.
                   Omit to show all active items (backlog + today + in_progress).
        item_type: Filter by type: task, article, video, course, dsa_problem, note, idea.
                   Omit to show all types.
        limit:     Max items to return. Default 10. Use higher values if the user asks
                   to "show everything" or "show all".
        sort_by:   Column to sort by. Options: "priority" (desc, default), "due_date" (asc),
                   "created_at" (desc). Default "priority".

    Returns:
        Formatted list of items with status icons, short IDs, priorities, effort,
        cognitive load, and due date warnings. Example:
            ○ [abc12345] p75 Review Casbin PR  (work/task) 30m medium [due in 2d]
            ◉ [def67890] p80 LeetCode #42 Two Sum  (interview_prep/dsa_problem) 45m high
        Returns "No items found." if the query returns nothing.
    """
    db = get_supabase()
    try:
        query = db.table("items").select("*")

        # Status filter — default to excluding done/archived
        if status:
            query = query.eq("status", status)
        else:
            query = query.not_.in_("status", ["done", "archived"])

        if category:
            query = query.eq("category", category)
        if item_type:
            query = query.eq("item_type", item_type)

        # Sorting
        if sort_by == "due_date":
            query = query.order("due_date", desc=False, nulls_last=True)
        elif sort_by == "created_at":
            query = query.order("created_at", desc=True)
        else:
            # Default: priority descending
            query = query.order("priority", desc=True)

        query = query.limit(limit)
        result = query.execute()

        if not result.data:
            return "No items found."

        lines = [_format_item(item) for item in result.data]
        header = f"Found {len(lines)} item(s):"
        return header + "\n" + "\n".join(lines)
    except Exception as e:
        return f"Error listing items: {e}"


@tool
def update_item(
    item_id: str,
    status: str | None = None,
    priority: int | None = None,
    title: str | None = None,
    notes: str | None = None,
    due_date: str | None = None,
    effort_minutes: int | None = None,
    cognitive_load: str | None = None,
    category: str | None = None,
    item_type: str | None = None,
) -> str:
    """Update fields on an existing item.

    Use this tool to:
    - Mark an item as done: update_item(item_id="abc12345", status="done")
    - Change priority: update_item(item_id="abc12345", priority=80)
    - Move to today: update_item(item_id="abc12345", status="today")
    - Add/update notes: update_item(item_id="abc12345", notes="figured out the approach")
    - Change due date: update_item(item_id="abc12345", due_date="tomorrow")

    IMPORTANT: If you don't know the item's ID, call search_items first to find it,
    then use the short ID from the search results.

    Args:
        item_id:        The item's ID — either the full UUID (36 chars) or a short ID
                        (first 8 chars from list/search output). Short IDs are resolved
                        via prefix matching.
        status:         New status: backlog, today, in_progress, done, archived.
                        Setting status="done" automatically sets completed_at to now.
        priority:       New priority integer 0–100.
        title:          New title (rename the item).
        notes:          New or updated notes text.
        due_date:       New deadline. Accepts "tomorrow", "+3d", "+3days", or ISO-8601.
                        Pass "none" or empty string to clear the due date.
        effort_minutes: Updated effort estimate in minutes.
        cognitive_load: Updated cognitive load: "low", "medium", or "high".
        category:       New category: work, interview_prep, learning, personal, hobby.
        item_type:      New item type: task, article, video, course, dsa_problem, note, idea.

    Returns:
        Confirmation of what was changed, e.g.:
        "Updated [abc12345] 'Review Casbin PR': status=done, completed_at=now"
        Returns an error if the item is not found.
    """
    db = get_supabase()
    try:
        # Resolve short ID → full UUID
        full_id: str | None = None
        if len(item_id) < 36:
            # Short ID: fetch recent IDs and match by prefix in Python
            # (PostgREST can't ILIKE on UUID columns without a cast)
            result = db.table("items").select("id, title").limit(500).execute()
            match = next(
                (r for r in (result.data or []) if r["id"].startswith(item_id)),
                None,
            )
            if not match:
                return (
                    f"Item not found with short ID '{item_id}'. "
                    "Use search_items to find the correct ID."
                )
            full_id = match["id"]
            item_title = match.get("title", "")
        else:
            full_id = item_id
            # Fetch title for confirmation message
            existing = (
                db.table("items").select("title").eq("id", full_id).limit(1).execute()
            )
            item_title = existing.data[0].get("title", "") if existing.data else ""

        # Build update payload
        updates: dict = {}
        changed: list[str] = []

        if status is not None:
            updates["status"] = status
            changed.append(f"status={status}")
            if status == "done":
                updates["completed_at"] = datetime.now(tz=timezone.utc).isoformat()
                changed.append("completed_at=now")

        if priority is not None:
            updates["priority"] = priority
            changed.append(f"priority={priority}")

        if title is not None:
            updates["title"] = title
            changed.append(f"title='{title}'")

        if notes is not None:
            updates["notes"] = notes
            changed.append("notes=updated")

        if due_date is not None:
            if due_date.strip().lower() in ("none", ""):
                updates["due_date"] = None
                changed.append("due_date=cleared")
            else:
                resolved = _resolve_due_date(due_date)
                updates["due_date"] = resolved
                changed.append(f"due_date={resolved[:10] if resolved else 'cleared'}")

        if effort_minutes is not None:
            updates["effort_minutes"] = effort_minutes
            changed.append(f"effort_minutes={effort_minutes}")

        if cognitive_load is not None:
            updates["cognitive_load"] = cognitive_load
            changed.append(f"cognitive_load={cognitive_load}")

        if category is not None:
            updates["category"] = category
            changed.append(f"category={category}")

        if item_type is not None:
            updates["item_type"] = item_type
            changed.append(f"item_type={item_type}")

        if not updates:
            return "Nothing to update — no fields were provided."

        db.table("items").update(updates).eq("id", full_id).execute()
        short_id = full_id[:8]
        changes_str = ", ".join(changed)
        return f"Updated [{short_id}] '{item_title}': {changes_str}"

    except Exception as e:
        return f"Error updating item: {e}"


@tool
def search_items(query: str) -> str:
    """Search for items by title using fuzzy matching.

    Use this tool when you need to find a specific item but don't have its ID.
    For example:
    - "find the Casbin PR task"
    - "mark the deploy script as done" → first search for "deploy script"
    - "what's the status of the kafka task?"

    Searches the title field using ILIKE (case-insensitive substring match).
    Excludes archived items. Returns up to 10 results sorted by priority.

    Args:
        query: Search string to match against item titles. Case-insensitive.
               Partial matches work — "casbin" will match "Review Casbin PR".
               Use keywords, not full sentences.

    Returns:
        Formatted list of matching items with short IDs, or "No items found."
        Use the short IDs in subsequent update_item calls.

        Example:
            Found 2 item(s):
            ▶ [abc12345] p75 Review Casbin PR  (work/task) 30m medium [due in 2d]
            ○ [def67890] p50 Read Casbin docs  (learning/article) 20m low
    """
    db = get_supabase()
    try:
        result = (
            db.table("items")
            .select("*")
            .ilike("title", f"%{query}%")
            .not_.eq("status", "archived")
            .order("priority", desc=True)
            .limit(10)
            .execute()
        )

        if not result.data:
            return f"No items found matching '{query}'."

        lines = [_format_item(item) for item in result.data]
        return f"Found {len(lines)} item(s) matching '{query}':\n" + "\n".join(lines)
    except Exception as e:
        return f"Error searching items: {e}"


@tool
def suggest_next(
    available_minutes: int = 60,
    energy_level: str | None = None,
    context: str | None = None,
) -> str:
    """Suggest the top 5 items for Akash to work on right now.

    Use this tool when the user asks:
    - "What should I do next?"
    - "What should I work on? I have 30 minutes."
    - "I'm tired, what's good for now?"
    - Any quick "what next?" question with optional time/energy constraints.

    The tool scores every active item using a composite algorithm that factors in:
    deadline urgency, career alignment, cognitive load vs current energy, whether
    the task fits in the available time, and recency. It returns the top 5 with
    a score and per-item explanation.

    IMPORTANT: The scoring is an INPUT to your reasoning, not the final answer.
    After receiving results, reason in your Thought step about whether the top
    scorer truly makes sense. Override it if context warrants (e.g. "scoring says
    DSA but he's been heads-down coding all day — take the video instead").

    Args:
        available_minutes: How many minutes Akash has right now. Default 60.
        energy_level:      Current energy: "high", "medium", or "low".
                           If omitted, inferred from IST hour:
                           06:00–11:59 → high, 12:00–16:59 → medium, 17:00+ → low.
        context:           Optional free-text context, e.g. "just finished a big task",
                           "feeling anxious about the interview". Used in formatting only.

    Returns:
        Ranked list of up to 5 items, each with score, short ID, and reason string.
        Example:
            1. [abc12345] p92→score122  Review Casbin PR  (work/task, 30m, medium)
               Why: base p92, +30 due today, +10 matches current focus
            2. [def67890] p80→score70  LRU Cache DSA  (interview_prep/dsa_problem, 45m, high)
               Why: base p80, +10 matches current focus, -20 high load + low energy
    """
    db = get_supabase()

    # ── Infer energy from IST hour if not provided ───────────────────────────
    if not energy_level:
        ist_offset = timedelta(hours=5, minutes=30)
        ist_now = datetime.now(tz=timezone.utc) + ist_offset
        hour = ist_now.hour
        if 6 <= hour < 12:
            energy_level = "high"
        elif 12 <= hour < 17:
            energy_level = "medium"
        else:
            energy_level = "low"

    # ── Load active items ────────────────────────────────────────────────────
    try:
        items_result = (
            db.table("items")
            .select("*")
            .not_.in_("status", ["done", "archived"])
            .execute()
        )
        items = items_result.data or []
    except Exception as e:
        return f"Error fetching items: {e}"

    if not items:
        return "No active items found in the backlog."

    # ── Load user_context ────────────────────────────────────────────────────
    focus_categories: list[str] = []
    career_goal = ""
    try:
        ctx_result = (
            db.table("user_context")
            .select("key, value")
            .in_("key", ["career_goal", "current_focus", "categories_active"])
            .execute()
        )
        for row in ctx_result.data or []:
            key = row["key"]
            val = row["value"]
            if key == "career_goal":
                career_goal = val if isinstance(val, str) else str(val)
            elif key == "current_focus":
                # current_focus is a string like "Backend engineering + interview prep"
                # derive categories from keywords
                focus_str = val if isinstance(val, str) else str(val)
                if "interview" in focus_str.lower():
                    focus_categories.append("interview_prep")
                if "work" in focus_str.lower() or "backend" in focus_str.lower():
                    focus_categories.append("work")
                if "learn" in focus_str.lower():
                    focus_categories.append("learning")
            elif key == "categories_active":
                # stored as JSON list or string
                if isinstance(val, list):
                    focus_categories.extend(val)
                elif isinstance(val, str):
                    try:
                        focus_categories.extend(json.loads(val))
                    except Exception:
                        pass
    except Exception:
        pass

    focus_categories = list(dict.fromkeys(focus_categories))  # deduplicate, preserve order

    scoring_context = {
        "energy": energy_level,
        "available_minutes": available_minutes,
        "current_focus_categories": focus_categories,
        "career_goal": career_goal,
    }

    ranked = rank_items(items, scoring_context)
    top5 = ranked[:5]

    # ── Format output ────────────────────────────────────────────────────────
    lines: list[str] = [
        f"Top suggestions ({energy_level} energy, {available_minutes}m available"
        + (f", context: {context}" if context else "")
        + "):"
    ]

    for idx, item in enumerate(top5, start=1):
        short_id = (item.get("id") or "")[:8]
        base_p = item.get("priority", 0)
        score = item.get("_score", base_p)
        reasons = item.get("_score_reasons", [])
        title = item.get("title", "(no title)")
        category = item.get("category", "")
        itype = item.get("item_type", "")
        effort = item.get("effort_minutes", "?")
        cog = item.get("cognitive_load", "")
        due_warn = _due_warning(item.get("due_date"))

        reason_str = ", ".join(reasons) if reasons else "no adjustments"
        lines.append(
            f"{idx}. [{short_id}] p{base_p}→score{int(score)}  {title}  "
            f"({category}/{itype}, {effort}m, {cog}){due_warn}"
        )
        lines.append(f"   Why: {reason_str}")

    return "\n".join(lines)


@tool
def plan_day(
    date: str = "today",
    total_hours: float = 8.0,
    energy_profile: str = "standard",
) -> str:
    """Build a time-blocked day plan that fits items into energy-appropriate blocks.

    Use this tool when the user asks for a structured plan:
    - "Plan my morning — I have 3 hours"
    - "What's my schedule for today?"
    - "Give me a full day plan"

    NOT for quick "what next?" questions — use suggest_next for those.

    The day is divided into three energy blocks:
        Morning  (high energy) → 40% of hours → high + medium cognitive load tasks
        Afternoon (medium)     → 35% of hours → medium + low cognitive load
        Evening  (low)         → 25% of hours → low cognitive load only (videos, articles)

    Items are greedy-fit into blocks by effort_minutes. A 15-minute break is inserted
    after every 90 consecutive minutes of scheduled work.

    Args:
        date:           "today" or any date string (display only). Default "today".
        total_hours:    Total available hours for the day. Default 8.0.
        energy_profile: "standard" uses the stored energy_pattern. Currently the only
                        supported value — pass "standard" or omit.

    Returns:
        Formatted time-blocked plan with block headers, item slots, and break markers.
    """
    db = get_supabase()

    # ── Load active items sorted by priority ─────────────────────────────────
    try:
        result = (
            db.table("items")
            .select("*")
            .in_("status", ["backlog", "today", "in_progress"])
            .order("priority", desc=True)
            .execute()
        )
        items = result.data or []
    except Exception as e:
        return f"Error fetching items: {e}"

    if not items:
        return "No active items to schedule."

    # ── Resolve start time from work_hours in user_context ───────────────────
    start_hour = 9  # default: 9 AM IST
    try:
        ctx = (
            db.table("user_context")
            .select("value")
            .eq("key", "work_hours")
            .limit(1)
            .execute()
        )
        if ctx.data:
            wh = ctx.data[0]["value"]
            wh_str = wh if isinstance(wh, str) else str(wh)
            start_str = wh_str.split("-")[0].strip()
            start_hour = int(start_str.split(":")[0])
    except Exception:
        pass

    # ── Block budgets (minutes) ───────────────────────────────────────────────
    total_minutes = int(total_hours * 60)
    morning_budget = int(total_minutes * 0.40)
    afternoon_budget = int(total_minutes * 0.35)
    evening_budget = total_minutes - morning_budget - afternoon_budget

    blocks = [
        {"name": "MORNING", "energy": "high", "budget": morning_budget,
         "allowed_loads": ["high", "medium"], "start_hour": start_hour},
        {"name": "AFTERNOON", "energy": "medium", "budget": afternoon_budget,
         "allowed_loads": ["medium", "low"], "start_hour": None},
        {"name": "EVENING", "energy": "low", "budget": evening_budget,
         "allowed_loads": ["low"], "start_hour": None},
    ]

    # ── Greedy fill ───────────────────────────────────────────────────────────
    scheduled: dict[str, list[dict]] = {b["name"]: [] for b in blocks}
    used_ids: set[str] = set()

    for block in blocks:
        remaining = block["budget"]
        for item in items:
            iid = item.get("id", "")
            if iid in used_ids:
                continue
            cog = item.get("cognitive_load", "medium")
            if cog not in block["allowed_loads"]:
                continue
            effort = item.get("effort_minutes") or 30
            if effort <= remaining:
                scheduled[block["name"]].append(item)
                used_ids.add(iid)
                remaining -= effort

    # ── Format output ─────────────────────────────────────────────────────────
    resolved_date = (
        datetime.now(tz=timezone.utc + timedelta(hours=5, minutes=30) if False else timezone.utc)
        .strftime("%Y-%m-%d")
        if date == "today"
        else date
    )

    lines: list[str] = [
        f"=== Day Plan: {resolved_date} ({total_hours}h available) ===",
    ]

    # Compute start time for morning block
    current_hour = start_hour
    current_min = 0
    total_morning_hours = morning_budget / 60
    total_afternoon_hours = afternoon_budget / 60

    for block in blocks:
        block_items = scheduled[block["name"]]
        block_minutes = block["budget"]
        block_hours = block_minutes / 60

        lines.append(
            f"\n{block['name']} ({block['energy']} energy, {block_hours:.1f}h)"
        )

        if not block_items:
            lines.append("  (nothing scheduled — block is free)")
        else:
            work_streak = 0
            for item in block_items:
                effort = item.get("effort_minutes") or 30
                title = item.get("title", "(no title)")
                category = item.get("category", "")
                itype = item.get("item_type", "")
                cog = item.get("cognitive_load", "")

                time_str = f"{current_hour:02d}:{current_min:02d}"
                lines.append(
                    f"  {time_str}  {title} — {effort}m  [{category}/{itype}, {cog} load]"
                )

                # Advance clock
                current_min += effort
                work_streak += effort
                current_hour += current_min // 60
                current_min = current_min % 60

                # Insert break after every 90 minutes of continuous work
                if work_streak >= 90:
                    time_str = f"{current_hour:02d}:{current_min:02d}"
                    lines.append(f"  {time_str}  -- Break 15m --")
                    current_min += 15
                    current_hour += current_min // 60
                    current_min = current_min % 60
                    work_streak = 0

        # Advance clock to next block start based on budget
        # (already advanced by items; just note transition)

    unscheduled = [i for i in items if i.get("id") not in used_ids]
    if unscheduled:
        lines.append(f"\nNot scheduled today ({len(unscheduled)} items remain in backlog):")
        for item in unscheduled[:5]:
            lines.append(f"  ○ p{item.get('priority',0)} {item.get('title','')}")
        if len(unscheduled) > 5:
            lines.append(f"  ... and {len(unscheduled) - 5} more")

    return "\n".join(lines)


@tool
def reprioritize(trigger: str) -> str:
    """Bulk-adjust item priorities based on a life-change trigger.

    Use this tool when the user signals a significant context shift:
    - "I'm starting to interview"          → boosts interview_prep, reduces hobby
    - "Big deadline moved to this Friday"  → boosts work tasks
    - "I'm burning out, need a break"      → reduces all, boosts personal
    - "I need to rest / take a break"      → same as burnout

    The tool loads all active items, computes adjustments based on trigger
    keywords, updates priorities in Supabase, and returns a human-readable
    summary of what changed.

    Keyword rules:
        "interview"                  → interview_prep +15, hobby -10
        "deadline" or "urgent"       → work +20
        "break", "rest", "burnout"   → all -10, personal +20

    Multiple rules can apply. Priority is clamped to [0, 100].

    Args:
        trigger: Natural language description of what changed, e.g.
                 "I've decided to start interviewing for new roles".

    Returns:
        Summary of changes, e.g.:
        "Reprioritized 12 items.
         interview_prep: avg 55→70 (+15). hobby: avg 40→30 (-10)."
    """
    db = get_supabase()

    try:
        result = (
            db.table("items")
            .select("*")
            .not_.in_("status", ["done", "archived"])
            .execute()
        )
        items = result.data or []
    except Exception as e:
        return f"Error loading items: {e}"

    if not items:
        return "No active items to reprioritize."

    trigger_lower = trigger.lower()

    # Determine adjustments per category
    adjustments: dict[str, int] = {}

    if "interview" in trigger_lower:
        adjustments["interview_prep"] = adjustments.get("interview_prep", 0) + 15
        adjustments["hobby"] = adjustments.get("hobby", 0) - 10

    if "deadline" in trigger_lower or "urgent" in trigger_lower:
        adjustments["work"] = adjustments.get("work", 0) + 20

    if any(w in trigger_lower for w in ("break", "rest", "burnout")):
        # Apply global -10 to everything then +20 to personal
        for cat in ["work", "interview_prep", "learning", "hobby"]:
            adjustments[cat] = adjustments.get(cat, 0) - 10
        adjustments["personal"] = adjustments.get("personal", 0) + 20

    if not adjustments:
        return (
            f"No automatic rule matched trigger: '{trigger}'. "
            "No changes applied. Try keywords: interview, deadline, urgent, break, rest, burnout."
        )

    # Group items by category to compute before/after averages
    by_category: dict[str, list[dict]] = {}
    for item in items:
        cat = item.get("category", "other")
        by_category.setdefault(cat, []).append(item)

    updates: list[dict] = []
    summary_parts: list[str] = []
    total_changed = 0

    for cat, delta in adjustments.items():
        cat_items = by_category.get(cat, [])
        if not cat_items:
            continue

        before_avg = sum(i.get("priority", 50) for i in cat_items) / len(cat_items)
        changed_in_cat = 0

        for item in cat_items:
            old_p = item.get("priority", 50)
            new_p = max(0, min(100, old_p + delta))
            if new_p != old_p:
                updates.append({"id": item["id"], "priority": new_p})
                changed_in_cat += 1

        if changed_in_cat:
            after_avg = before_avg + delta
            after_avg = max(0, min(100, after_avg))
            sign = "+" if delta > 0 else ""
            summary_parts.append(
                f"{cat}: avg {before_avg:.0f}→{after_avg:.0f} ({sign}{delta})"
            )
            total_changed += changed_in_cat

    # Apply updates
    failed = 0
    for upd in updates:
        try:
            db.table("items").update({"priority": upd["priority"]}).eq("id", upd["id"]).execute()
        except Exception:
            failed += 1

    if failed:
        summary_parts.append(f"({failed} updates failed)")

    if not total_changed:
        return f"Trigger '{trigger}' matched rules but no items needed priority changes."

    summary = f"Reprioritized {total_changed} item(s) based on: '{trigger}'.\n"
    summary += "  " + ". ".join(summary_parts) + "."
    return summary


@tool
def get_stats(period: str = "week") -> str:
    """Return productivity statistics for a given time period.

    Call this tool BEFORE saying things like "you've been productive" or
    "you should take a break" — verify with data first.

    Also use when the user asks:
    - "How productive was I this week?"
    - "What did I complete today?"
    - "What's my current backlog?"
    - "Show me my streak"

    Args:
        period: One of "today", "week", "month". Default "week".
                "today"  → completed items from the last 24 hours
                "week"   → completed items from the last 7 days
                "month"  → completed items from the last 30 days

    Returns:
        Human-readable summary including:
        - Items completed (total + by category) with total effort minutes
        - Current backlog size by category
        - Completion streak (consecutive days with at least 1 completion)
    """
    db = get_supabase()

    now = datetime.now(tz=timezone.utc)
    period_map = {"today": 1, "week": 7, "month": 30}
    days_back = period_map.get(period, 7)
    since = (now - timedelta(days=days_back)).isoformat()

    # ── Completed items in period ─────────────────────────────────────────────
    try:
        done_result = (
            db.table("items")
            .select("category, effort_minutes, completed_at")
            .eq("status", "done")
            .gte("completed_at", since)
            .execute()
        )
        done_items = done_result.data or []
    except Exception as e:
        return f"Error fetching completed items: {e}"

    by_cat_done: dict[str, dict] = {}
    total_effort = 0
    for item in done_items:
        cat = item.get("category", "unknown")
        effort = item.get("effort_minutes") or 0
        if cat not in by_cat_done:
            by_cat_done[cat] = {"count": 0, "effort": 0}
        by_cat_done[cat]["count"] += 1
        by_cat_done[cat]["effort"] += effort
        total_effort += effort

    # ── Active backlog by category ────────────────────────────────────────────
    try:
        backlog_result = (
            db.table("items")
            .select("category")
            .not_.in_("status", ["done", "archived"])
            .execute()
        )
        backlog_items = backlog_result.data or []
    except Exception as e:
        backlog_items = []

    backlog_by_cat: dict[str, int] = {}
    for item in backlog_items:
        cat = item.get("category", "unknown")
        backlog_by_cat[cat] = backlog_by_cat.get(cat, 0) + 1

    # ── Streak calculation ────────────────────────────────────────────────────
    streak = 0
    try:
        streak_result = (
            db.table("items")
            .select("completed_at")
            .eq("status", "done")
            .not_.is_("completed_at", "null")
            .order("completed_at", desc=True)
            .limit(200)
            .execute()
        )
        completion_dates: set[str] = set()
        for row in streak_result.data or []:
            ca = row.get("completed_at", "")
            if ca:
                try:
                    dt = datetime.fromisoformat(ca.replace("Z", "+00:00"))
                    completion_dates.add(dt.date().isoformat())
                except Exception:
                    pass

        # Count consecutive days ending today
        check_date = now.date()
        while check_date.isoformat() in completion_dates:
            streak += 1
            check_date -= timedelta(days=1)
    except Exception:
        pass

    # ── Build output ──────────────────────────────────────────────────────────
    period_label = {"today": "today", "week": "last 7 days", "month": "last 30 days"}.get(
        period, f"last {days_back} days"
    )

    lines: list[str] = [
        f"=== Stats: {period_label} ===",
        "",
        f"Completed: {len(done_items)} item(s), ~{total_effort}m of work logged",
    ]

    if by_cat_done:
        for cat, stats in sorted(by_cat_done.items(), key=lambda x: -x[1]["count"]):
            lines.append(f"  {cat}: {stats['count']} done, ~{stats['effort']}m")
    else:
        lines.append("  (none completed in this period)")

    lines.append("")
    lines.append(f"Active backlog: {len(backlog_items)} item(s)")
    if backlog_by_cat:
        for cat, count in sorted(backlog_by_cat.items(), key=lambda x: -x[1]):
            lines.append(f"  {cat}: {count}")

    lines.append("")
    if streak == 0:
        lines.append("Streak: 0 days — no completions today yet.")
    elif streak == 1:
        lines.append("Streak: 1 day — good start, keep it going!")
    else:
        lines.append(f"Streak: {streak} days in a row! Keep it going.")

    return "\n".join(lines)


@tool
def update_my_context(key: str, value: str) -> str:
    """Update a key in the user_context table (long-term agent memory).

    Use this tool to persist life-changes detected in conversation:
    - When user says "I'm interviewing now" → update current_focus
    - When user changes energy pattern → update energy_pattern
    - When user updates career goal → update career_goal

    Proactively call this (along with reprioritize) whenever the user signals
    a significant change in priorities, focus, or life situation. Do NOT wait
    to be asked — persist the change so future sessions remember it.

    Common keys (all stored in user_context table):
        career_goal       — e.g. "Get a senior backend role at a top startup"
        current_focus     — e.g. "Interview preparation + current work"
        energy_pattern    — e.g. "morning=high, afternoon=medium, evening=low"
        work_hours        — e.g. "10:00-19:00 IST"
        categories_active — e.g. "work,interview_prep,learning"

    Args:
        key:   The user_context key to set or update.
        value: New string value. Stored as a JSON string in the value column.

    Returns:
        Confirmation of the upsert, e.g.:
        "Updated user_context: current_focus = 'Interview preparation + current work'"
    """
    db = get_supabase()
    try:
        db.table("user_context").upsert(
            {"key": key, "value": json.dumps(value)},
            on_conflict="key",
        ).execute()
        return f"Updated user_context: {key} = '{value}'"
    except Exception as e:
        return f"Error updating user_context key '{key}': {e}"


# Exported list — passed to LLM.bind_tools() and ToolNode
ALL_TOOLS = [
    add_item,
    list_items,
    update_item,
    search_items,
    suggest_next,
    plan_day,
    reprioritize,
    get_stats,
    update_my_context,
]
