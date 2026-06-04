"""
LangChain @tool functions for the akash-planner ReAct agent.

Tools exported:
    add_item           — insert a new item into the backlog
    list_items         — list items with filters and formatted output
    update_item        — update fields on an existing item
    search_items       — full-text search on item titles
    suggest_next       — score + rank items for the current moment
    plan_day           — build a time-blocked day plan
    reprioritize       — bulk-adjust priorities based on a life-change trigger
    get_stats          — productivity stats for today/week/month
    update_my_context  — update user_context key-value store
    archive_done_items — archive done items older than 2 days
    get_my_context     — load all user context rows

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
    """Add a new item to Akash's backlog. title/category/item_type required; all other fields have sensible defaults."""
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
    """List items from the backlog with optional filters. Excludes done/archived by default unless status is passed."""
    db = get_supabase()
    try:
        query = db.table("items").select("*")

        if status:
            query = query.eq("status", status)
        else:
            query = query.not_.in_("status", ["done", "archived"])

        if category:
            query = query.eq("category", category)
        if item_type:
            query = query.eq("item_type", item_type)

        if sort_by == "due_date":
            query = query.order("due_date", desc=False, nulls_last=True)
        elif sort_by == "created_at":
            query = query.order("created_at", desc=True)
        else:
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
    progress_percent: int | None = None,
) -> str:
    """Update fields on an existing item by short or full ID. Search first if you don't have the ID."""
    db = get_supabase()
    try:
        full_id: str | None = None
        if len(item_id) < 36:
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
            existing = (
                db.table("items").select("title").eq("id", full_id).limit(1).execute()
            )
            item_title = existing.data[0].get("title", "") if existing.data else ""

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

        if progress_percent is not None:
            updates["progress_percent"] = progress_percent
            changed.append(f"progress_percent={progress_percent}")
            # Auto-set in_progress when partial progress is recorded and status not explicitly set
            if progress_percent > 0 and status is None:
                updates["status"] = "in_progress"
                changed.append("status=in_progress")

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
    """Search items by title (case-insensitive substring). Returns short IDs for use in update_item."""
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
    """Suggest the top 5 items to work on right now, scored by deadline urgency, energy fit, and career alignment."""
    db = get_supabase()

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
                focus_str = val if isinstance(val, str) else str(val)
                if "interview" in focus_str.lower():
                    focus_categories.append("interview_prep")
                if "work" in focus_str.lower() or "backend" in focus_str.lower():
                    focus_categories.append("work")
                if "learn" in focus_str.lower():
                    focus_categories.append("learning")
            elif key == "categories_active":
                if isinstance(val, list):
                    focus_categories.extend(val)
                elif isinstance(val, str):
                    try:
                        focus_categories.extend(json.loads(val))
                    except Exception:
                        pass
    except Exception:
        pass

    focus_categories = list(dict.fromkeys(focus_categories))

    scoring_context = {
        "energy": energy_level,
        "available_minutes": available_minutes,
        "current_focus_categories": focus_categories,
        "career_goal": career_goal,
    }

    ranked = rank_items(items, scoring_context)
    top5 = ranked[:5]

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
    """Build a time-blocked day plan. Use for full/morning schedule requests; use suggest_next for quick "what next?" questions."""
    db = get_supabase()

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

    start_hour = 9
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

    resolved_date = (
        datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
        if date == "today"
        else date
    )

    lines: list[str] = [
        f"=== Day Plan: {resolved_date} ({total_hours}h available) ===",
    ]

    current_hour = start_hour
    current_min = 0

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

                current_min += effort
                work_streak += effort
                current_hour += current_min // 60
                current_min = current_min % 60

                if work_streak >= 90:
                    time_str = f"{current_hour:02d}:{current_min:02d}"
                    lines.append(f"  {time_str}  -- Break 15m --")
                    current_min += 15
                    current_hour += current_min // 60
                    current_min = current_min % 60
                    work_streak = 0

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
    """Bulk-adjust item priorities based on a life-change trigger (e.g. 'I'm interviewing', 'big deadline', 'need a break')."""
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

    adjustments: dict[str, int] = {}

    if "interview" in trigger_lower:
        adjustments["interview_prep"] = adjustments.get("interview_prep", 0) + 15
        adjustments["hobby"] = adjustments.get("hobby", 0) - 10

    if "deadline" in trigger_lower or "urgent" in trigger_lower:
        adjustments["work"] = adjustments.get("work", 0) + 20

    if any(w in trigger_lower for w in ("break", "rest", "burnout")):
        for cat in ["work", "interview_prep", "learning", "hobby"]:
            adjustments[cat] = adjustments.get(cat, 0) - 10
        adjustments["personal"] = adjustments.get("personal", 0) + 20

    if not adjustments:
        return (
            f"No automatic rule matched trigger: '{trigger}'. "
            "No changes applied. Try keywords: interview, deadline, urgent, break, rest, burnout."
        )

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
    """Return productivity stats (completed count, effort, backlog size, streak) for 'today', 'week', or 'month'."""
    db = get_supabase()

    now = datetime.now(tz=timezone.utc)
    period_map = {"today": 1, "week": 7, "month": 30}
    days_back = period_map.get(period, 7)
    since = (now - timedelta(days=days_back)).isoformat()

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

        check_date = now.date()
        while check_date.isoformat() in completion_dates:
            streak += 1
            check_date -= timedelta(days=1)
    except Exception:
        pass

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
    """Update a key in the user_context table (long-term memory). Call with reprioritize on life changes."""
    db = get_supabase()
    try:
        db.table("user_context").upsert(
            {"key": key, "value": json.dumps(value)},
            on_conflict="key",
        ).execute()
        return f"Updated user_context: {key} = '{value}'"
    except Exception as e:
        return f"Error updating user_context key '{key}': {e}"


@tool
def archive_done_items() -> str:
    """Archive all 'done' items that were completed more than 2 days ago."""
    db = get_supabase()
    cutoff = (datetime.now(tz=timezone.utc) - timedelta(days=2)).isoformat()
    try:
        # Items done with a completed_at older than cutoff, or done but completed_at is null
        result = (
            db.table("items")
            .select("id")
            .eq("status", "done")
            .or_(f"completed_at.lt.{cutoff},completed_at.is.null")
            .execute()
        )
        ids = [row["id"] for row in (result.data or [])]
        if not ids:
            return "No done items older than 2 days to archive."

        db.table("items").update({"status": "archived"}).in_("id", ids).execute()
        return f"Archived {len(ids)} item(s)."
    except Exception as e:
        return f"Error archiving done items: {e}"


@tool
def get_my_context() -> str:
    """Load all user context (career goal, current focus, energy pattern, work hours). Call this at the start of each session."""
    db = get_supabase()
    try:
        result = db.table("user_context").select("key, value").execute()
        rows = result.data or []
        if not rows:
            return "No user context found."
        lines = []
        for row in rows:
            key = row.get("key", "")
            val = row.get("value", "")
            # value is stored as JSON — unwrap strings
            if isinstance(val, str):
                try:
                    val = json.loads(val)
                except Exception:
                    pass
            lines.append(f"{key}: {val}")
        return "\n".join(lines)
    except Exception as e:
        return f"Error loading user context: {e}"


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
    archive_done_items,
    get_my_context,
]
