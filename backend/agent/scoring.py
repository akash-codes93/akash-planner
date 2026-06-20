"""
Priority scoring engine for the akash-planner ReAct agent.

Computes composite scores for items based on:
- Base priority stored in the database
- Deadline urgency (overdue → today → tomorrow → 3 days)
- Career alignment with current focus categories
- Cognitive load vs current energy mismatch penalty
- Time availability overflow penalty
- Recency bonus for freshly added items

Public API:
    score_item(item, context) -> float
    rank_items(items, context) -> list[dict]
"""

from datetime import datetime, timedelta, timezone


def score_item(item: dict, context: dict) -> tuple[float, list[str]]:
    """Compute a composite priority score for a single item.

    Args:
        item: A dict representing one row from the items table. Expected keys:
              priority, due_date, category, cognitive_load, effort_minutes, created_at.
        context: Runtime context dict with keys:
              energy                   — "high" | "medium" | "low"
              available_minutes        — int, how many minutes the user has now
              current_focus_categories — list[str], e.g. ["interview_prep", "work"]
              career_goal              — str, used for reasoning (not scored directly)

    Returns:
        Tuple of (score: float, reasons: list[str]) where reasons explains each
        scoring component that contributed a non-zero delta.

    Score formula:
        base_priority
        + deadline_urgency   (+50 overdue, +30 today, +20 tomorrow, +10 in 3 days)
        + career_alignment   (+10 if category in current_focus_categories)
        - cognitive_mismatch (-20 if high load + low energy, -10 if high load + medium energy)
        - time_overflow      (-15 if effort_minutes > available_minutes)
        + recency_bonus      (+5 if created within last 24 hours)
    """
    now = datetime.now(tz=timezone.utc)
    reasons: list[str] = []

    # ── Base priority ────────────────────────────────────────────────────────
    score: float = float(item.get("priority", 50))
    reasons.append(f"base p{int(score)}")

    # ── Deadline urgency ─────────────────────────────────────────────────────
    due_date_str: str | None = item.get("due_date")
    if due_date_str:
        try:
            due_dt = datetime.fromisoformat(due_date_str.replace("Z", "+00:00"))
            delta_days = (due_dt.date() - now.date()).days
            if delta_days < 0:
                score += 50
                reasons.append("+50 overdue")
            elif delta_days == 0:
                score += 30
                reasons.append("+30 due today")
            elif delta_days == 1:
                score += 20
                reasons.append("+20 due tomorrow")
            elif delta_days <= 3:
                score += 10
                reasons.append("+10 due in 3 days")
        except (ValueError, TypeError):
            pass

    # ── Career alignment ─────────────────────────────────────────────────────
    focus_categories: list[str] = context.get("current_focus_categories", [])
    item_category: str = item.get("category", "")
    if item_category and item_category in focus_categories:
        score += 10
        reasons.append("+10 matches current focus")

    # ── Cognitive load vs energy mismatch ────────────────────────────────────
    cognitive_load: str = item.get("cognitive_load", "medium")
    energy: str = context.get("energy", "medium")
    if cognitive_load == "high" and energy == "low":
        score -= 20
        reasons.append("-20 high load + low energy")
    elif cognitive_load == "high" and energy == "medium":
        score -= 10
        reasons.append("-10 high load + medium energy")

    # ── Time overflow penalty ─────────────────────────────────────────────────
    effort_minutes: int | None = item.get("effort_minutes")
    available_minutes: int = context.get("available_minutes", 0)
    if effort_minutes and 0 < available_minutes < effort_minutes:
        score -= 15
        reasons.append(f"-15 effort {effort_minutes}m > available {available_minutes}m")

    # ── Recency bonus ────────────────────────────────────────────────────────
    created_at_str: str | None = item.get("created_at")
    if created_at_str:
        try:
            created_dt = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
            if (now - created_dt) <= timedelta(hours=24):
                score += 5
                reasons.append("+5 added in last 24h")
        except (ValueError, TypeError):
            pass

    return score, reasons


def rank_items(items: list[dict], context: dict) -> list[dict]:
    """Score all items and return them sorted by score descending.

    Each item dict in the returned list gets two extra keys added in-place:
        _score         — the computed float score
        _score_reasons — list[str] explaining each scoring component

    Args:
        items:   List of item dicts from the items table.
        context: Runtime context dict (see score_item for shape).

    Returns:
        New list of item dicts sorted by _score descending. Original dicts
        are mutated to add _score/_score_reasons — do not rely on original order.
    """
    scored: list[dict] = []
    for item in items:
        s, reasons = score_item(item, context)
        enriched = dict(item)
        enriched["_score"] = s
        enriched["_score_reasons"] = reasons
        scored.append(enriched)

    scored.sort(key=lambda x: x["_score"], reverse=True)
    return scored
