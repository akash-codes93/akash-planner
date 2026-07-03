from __future__ import annotations

import json
import os
import re
import sqlite3
import urllib.error
import urllib.request
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


DB_PATH = Path(os.environ.get("PLANNER_DB_PATH", Path(__file__).resolve().parents[1] / "planner.sqlite3"))
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434/api/generate")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:7b")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:12]}"


@contextmanager
def _connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


TASK_COLUMNS = (
    "id",
    "parent_task_id",
    "title",
    "description",
    "status",
    "due_at",
    "completed_at",
    "archived_at",
    "created_at",
    "updated_at",
)
TASK_COLUMNS_SQL = ", ".join(f"t.{column}" for column in TASK_COLUMNS)


def init_db() -> None:
    with _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS goals (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'active',
                priority INTEGER NOT NULL DEFAULT 50,
                progress_percent INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'backlog',
                due_at TEXT,
                completed_at TEXT,
                archived_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS tags (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL UNIQUE
            );

            CREATE TABLE IF NOT EXISTS task_tags (
                task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                tag_id TEXT NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
                PRIMARY KEY (task_id, tag_id)
            );

            CREATE TABLE IF NOT EXISTS llm_action_drafts (
                id TEXT PRIMARY KEY,
                action_type TEXT NOT NULL,
                input_text TEXT NOT NULL,
                proposed_payload_json TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                confirmed_at TEXT
            );

            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS activity_log (
                date TEXT PRIMARY KEY,
                count INTEGER NOT NULL DEFAULT 0,
                minutes INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS streak_freezes (
                date_used TEXT PRIMARY KEY
            );
            """
        )
        # Additive migrations for sqlite files created before these columns/tables existed.
        # Safe to run even on a fresh db (no-ops there since the columns already exist).
        _ensure_column(conn, "tasks", "completed_at", "TEXT")
        _ensure_column(conn, "tasks", "archived_at", "TEXT")
        _ensure_column(conn, "tasks", "parent_task_id", "TEXT REFERENCES tasks(id) ON DELETE CASCADE")
        _ensure_column(conn, "llm_action_drafts", "confirmed_at", "TEXT")
        count = conn.execute("SELECT COUNT(*) AS count FROM tasks").fetchone()["count"]
        seed_disabled = conn.execute(
            "SELECT value FROM app_settings WHERE key = ?",
            ("seed_disabled",),
        ).fetchone()
        if count == 0 and not seed_disabled:
            seed(conn)


def seed(conn: sqlite3.Connection) -> None:
    now = _now()
    tasks = [
        (
            "task-payments",
            "Prepare payment system design",
            "Cover lifecycle, idempotency, ledger, reconciliation, retries, and failure handling.",
            None,
            ["Career", "Interview"],
        ),
        (
            "task-redis",
            "Study Redis set vs sorted set",
            "Understand operations, use cases, and tradeoffs.",
            None,
            ["Learning", "Redis"],
        ),
        (
            "task-sprint",
            "Plan next sprint execution",
            "Group tasks into must-ship, risk, and follow-up.",
            now,
            ["Work"],
        ),
        (
            "task-observability",
            "Design API latency dashboard",
            "Define metrics, panels, and alert thresholds.",
            None,
            ["Work"],
        ),
        (
            "task-kafka",
            "Deep dive Kafka consumer rebalancing",
            "Study assignment strategies and failure behavior.",
            None,
            ["Career", "Learning"],
        ),
    ]
    for task_id, title, description, due_at, tag_names in tasks:
        conn.execute(
            """
            INSERT INTO tasks (id, title, description, status, due_at, created_at, updated_at)
            VALUES (?, ?, ?, 'backlog', ?, ?, ?)
            """,
            (task_id, title, description, due_at, now, now),
        )
        for tag_name in tag_names:
            tag = _get_or_create_tag_conn(conn, tag_name)
            if tag:
                conn.execute(
                    "INSERT OR IGNORE INTO task_tags (task_id, tag_id) VALUES (?, ?)",
                    (task_id, tag["id"]),
                )


# ---------------------------------------------------------------------------
# Tags
# ---------------------------------------------------------------------------


def _get_or_create_tag_conn(conn: sqlite3.Connection, name: str) -> dict[str, Any] | None:
    cleaned = (name or "").strip()
    if not cleaned:
        return None
    row = conn.execute("SELECT id, name FROM tags WHERE name = ? COLLATE NOCASE", (cleaned,)).fetchone()
    if row:
        return dict(row)
    tag_id = _id("tag")
    conn.execute("INSERT INTO tags (id, name) VALUES (?, ?)", (tag_id, cleaned))
    return {"id": tag_id, "name": cleaned}


def list_tags() -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute("SELECT id, name FROM tags ORDER BY name COLLATE NOCASE").fetchall()
        return [dict(row) for row in rows]


def get_or_create_tag(name: str) -> dict[str, Any]:
    with _connect() as conn:
        tag = _get_or_create_tag_conn(conn, name)
        if tag is None:
            raise ValueError("Tag name is required")
        return tag


def _resolve_tag_ids_conn(
    conn: sqlite3.Connection,
    tag_ids: list[str] | None,
    tag_names: list[str] | None,
) -> list[str]:
    resolved: list[str] = []
    seen: set[str] = set()
    for tag_id in tag_ids or []:
        row = conn.execute("SELECT id FROM tags WHERE id = ?", (tag_id,)).fetchone()
        if row and row["id"] not in seen:
            resolved.append(row["id"])
            seen.add(row["id"])
    for name in tag_names or []:
        tag = _get_or_create_tag_conn(conn, name)
        if tag and tag["id"] not in seen:
            resolved.append(tag["id"])
            seen.add(tag["id"])
    return resolved


def _set_task_tags_conn(conn: sqlite3.Connection, task_id: str, tag_ids: list[str]) -> None:
    conn.execute("DELETE FROM task_tags WHERE task_id = ?", (task_id,))
    for tag_id in tag_ids:
        conn.execute(
            "INSERT OR IGNORE INTO task_tags (task_id, tag_id) VALUES (?, ?)",
            (task_id, tag_id),
        )


def _get_task_tags_conn(conn: sqlite3.Connection, task_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT tags.id AS id, tags.name AS name
        FROM tags
        JOIN task_tags ON task_tags.tag_id = tags.id
        WHERE task_tags.task_id = ?
        ORDER BY tags.name COLLATE NOCASE
        """,
        (task_id,),
    ).fetchall()
    return [dict(row) for row in rows]


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------


def _query_tasks(
    conn: sqlite3.Connection,
    parent_task_id: str | None,
    status: str | None,
    include_archived: bool,
) -> list[dict[str, Any]]:
    where = []
    params: list[Any] = []
    if not include_archived:
        where.append("t.archived_at IS NULL")
    if status:
        where.append("t.status = ?")
        params.append(status)
    if parent_task_id is not None:
        where.append("t.parent_task_id = ?")
        params.append(parent_task_id)
    else:
        where.append("t.parent_task_id IS NULL")
    where_clause = f"WHERE {' AND '.join(where)}"
    rows = conn.execute(
        f"""
        SELECT {TASK_COLUMNS_SQL}
        FROM tasks t
        {where_clause}
        ORDER BY
            CASE t.status WHEN 'backlog' THEN 0 WHEN 'done' THEN 1 ELSE 2 END,
            CASE WHEN t.due_at IS NULL THEN 1 ELSE 0 END,
            t.due_at ASC,
            t.created_at DESC
        """,
        params,
    ).fetchall()
    tasks = [dict(row) for row in rows]
    for task in tasks:
        task["tags"] = _get_task_tags_conn(conn, task["id"])
    return tasks


def list_tasks(
    tag_id: str | None = None,
    status: str | None = None,
    include_archived: bool = False,
    parent_task_id: str | None = None,
    with_subtasks: bool = False,
) -> list[dict[str, Any]]:
    with _connect() as conn:
        tasks = _query_tasks(conn, parent_task_id, status, include_archived)
        need_subtasks = (with_subtasks or bool(tag_id)) and parent_task_id is None
        if need_subtasks:
            for task in tasks:
                task["subtasks"] = _query_tasks(conn, task["id"], None, include_archived)

        if tag_id:
            def matches(task: dict[str, Any]) -> bool:
                if any(tag["id"] == tag_id for tag in task["tags"]):
                    return True
                return any(
                    any(tag["id"] == tag_id for tag in sub["tags"])
                    for sub in task.get("subtasks", [])
                )

            tasks = [task for task in tasks if matches(task)]
            # Keep the (already-fetched) subtasks nested so a subtask that only matches
            # via its own tag is still visible under its parent, per the "never orphan
            # a matching subtask" filtering rule — even if with_subtasks wasn't asked for.

        return tasks


def get_task(task_id: str) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute(
            f"SELECT {', '.join(TASK_COLUMNS)} FROM tasks WHERE id = ?",
            (task_id,),
        ).fetchone()
        if row is None:
            return None
        data = dict(row)
        data["tags"] = _get_task_tags_conn(conn, task_id)
        subtask_rows = conn.execute(
            f"""
            SELECT {', '.join(TASK_COLUMNS)}
            FROM tasks
            WHERE parent_task_id = ?
            ORDER BY created_at ASC
            """,
            (task_id,),
        ).fetchall()
        subtasks = [dict(sub_row) for sub_row in subtask_rows]
        for subtask in subtasks:
            subtask["tags"] = _get_task_tags_conn(conn, subtask["id"])
        data["subtasks"] = subtasks
        return data


def create_task(payload: dict[str, Any]) -> dict[str, Any]:
    task_id = payload.get("id") or _id("task")
    parent_task_id = payload.get("parent_task_id")
    now = _now()
    with _connect() as conn:
        tag_ids = _resolve_tag_ids_conn(conn, payload.get("tag_ids"), payload.get("tag_names"))
        conn.execute(
            """
            INSERT INTO tasks (id, parent_task_id, title, description, status, due_at, created_at, updated_at)
            VALUES (?, ?, ?, ?, 'backlog', ?, ?, ?)
            """,
            (
                task_id,
                parent_task_id,
                payload["title"],
                payload.get("description", ""),
                payload.get("due_at"),
                now,
                now,
            ),
        )
        if tag_ids:
            _set_task_tags_conn(conn, task_id, tag_ids)
    record_activity()
    return get_task(task_id) or {}


def update_task(task_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    allowed = {"title", "description", "status", "due_at", "completed_at", "archived_at"}
    updates = {key: value for key, value in payload.items() if key in allowed}
    if updates.get("status") == "done":
        updates.setdefault("completed_at", _now())
    elif updates.get("status") == "backlog":
        updates.setdefault("completed_at", None)

    with _connect() as conn:
        if updates:
            assignments = ", ".join(f"{key} = ?" for key in updates)
            values = list(updates.values()) + [_now(), task_id]
            conn.execute(f"UPDATE tasks SET {assignments}, updated_at = ? WHERE id = ?", values)
        if "tag_ids" in payload or "tag_names" in payload:
            tag_ids = _resolve_tag_ids_conn(conn, payload.get("tag_ids"), payload.get("tag_names"))
            _set_task_tags_conn(conn, task_id, tag_ids)
    return get_task(task_id)


def complete_task(task_id: str) -> dict[str, Any] | None:
    task = get_task(task_id)
    if task is None:
        return None
    if task["status"] == "done":
        return task

    update_task(task_id, {"status": "done", "completed_at": _now()})
    record_activity()

    parent_task_id = task.get("parent_task_id")
    if parent_task_id:
        siblings = list_tasks(parent_task_id=parent_task_id, include_archived=True)
        if siblings and all(sibling["status"] == "done" for sibling in siblings):
            parent = get_task(parent_task_id)
            if parent and parent["status"] != "done":
                complete_task(parent_task_id)

    return get_task(task_id)


def archive_task(task_id: str) -> dict[str, Any] | None:
    return update_task(task_id, {"archived_at": _now()})


def delete_task(task_id: str) -> bool:
    with _connect() as conn:
        cursor = conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        return cursor.rowcount > 0


def clear_workspace() -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM llm_action_drafts")
        conn.execute("DELETE FROM task_tags")
        conn.execute("DELETE FROM tasks")
        conn.execute("DELETE FROM tags")
        conn.execute("DELETE FROM goals")
        conn.execute("DELETE FROM activity_log")
        conn.execute("DELETE FROM streak_freezes")
        conn.execute(
            "INSERT OR REPLACE INTO app_settings (key, value) VALUES (?, ?)",
            ("seed_disabled", "true"),
        )


# ---------------------------------------------------------------------------
# Activity / streaks (unchanged)
# ---------------------------------------------------------------------------


def _today_key() -> str:
    return _now()[:10]


def record_activity(minutes: int = 0) -> None:
    date_key = _today_key()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO activity_log (date, count, minutes) VALUES (?, 1, ?)
            ON CONFLICT(date) DO UPDATE SET count = count + 1, minutes = minutes + excluded.minutes
            """,
            (date_key, minutes),
        )


def _freeze_token_available(freeze_dates: set[date], today: date) -> bool:
    window_start = today - timedelta(days=6)
    return not any(window_start <= freeze_date <= today for freeze_date in freeze_dates)


def _compute_streak(
    counts: dict[str, int],
    freeze_dates: set[date],
    today: date,
    max_days: int = 400,
) -> tuple[int, bool, date | None]:
    def activity_count(day: date) -> int:
        return counts.get(day.isoformat(), 0)

    if activity_count(today) > 0:
        cursor: date | None = today
    elif activity_count(today - timedelta(days=1)) > 0 or (today - timedelta(days=1)) in freeze_dates:
        cursor = today - timedelta(days=1)
    else:
        cursor = None

    streak = 0
    newly_frozen: date | None = None
    gap_used_this_walk = False
    earliest = today - timedelta(days=max_days)
    # Days before the earliest recorded activity (or freeze) row are "no history", not
    # genuine idle days, so they must never be treated as a freezable gap.
    recorded_dates = [date.fromisoformat(day) for day in counts] + list(freeze_dates)
    earliest_recorded = min(recorded_dates) if recorded_dates else today

    while cursor is not None and cursor >= earliest:
        if activity_count(cursor) > 0:
            streak += 1
            cursor -= timedelta(days=1)
            continue
        if cursor in freeze_dates:
            # Previously-frozen gap day: chain stays unbroken, but does not add to the count.
            cursor -= timedelta(days=1)
            continue
        if cursor < earliest_recorded:
            break
        if gap_used_this_walk:
            break
        window_start = cursor - timedelta(days=6)
        used_recently = any(window_start <= freeze_date <= cursor for freeze_date in freeze_dates)
        within_recent_window = cursor >= today - timedelta(days=7)
        if within_recent_window and not used_recently:
            gap_used_this_walk = True
            newly_frozen = cursor
            cursor -= timedelta(days=1)
            continue
        break

    effective_freeze_dates = freeze_dates | ({newly_frozen} if newly_frozen else set())
    freeze_available = _freeze_token_available(effective_freeze_dates, today)
    return streak, freeze_available, newly_frozen


def get_activity(days: int = 90) -> dict[str, Any]:
    with _connect() as conn:
        activity_rows = conn.execute("SELECT date, count FROM activity_log").fetchall()
        freeze_rows = conn.execute("SELECT date_used FROM streak_freezes").fetchall()

    counts = {row["date"]: int(row["count"]) for row in activity_rows}
    freeze_dates = {date.fromisoformat(row["date_used"]) for row in freeze_rows}
    today = datetime.now(timezone.utc).date()

    streak, freeze_available, newly_frozen = _compute_streak(counts, freeze_dates, today)
    if newly_frozen is not None:
        with _connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO streak_freezes (date_used) VALUES (?)",
                (newly_frozen.isoformat(),),
            )

    day_list = [(today - timedelta(days=offset)).isoformat() for offset in range(days - 1, -1, -1)]
    return {
        "days": [{"date": day, "count": counts.get(day, 0)} for day in day_list],
        "streak": streak,
        "freeze_available": freeze_available,
    }


# ---------------------------------------------------------------------------
# Dashboard / suggestions / due signals
# ---------------------------------------------------------------------------


def dashboard() -> dict[str, Any]:
    tags = list_tags()
    tasks = list_tasks()
    active_tasks = [task for task in tasks if task["status"] != "done"]
    next_tasks = suggest_next_tasks(5)
    due = due_buckets(tasks)
    return {
        "stats": {
            "tags": len(tags),
            "active_tasks": len(active_tasks),
            "due_soon": len(due["due_soon"]),
            "overdue": len(due["overdue"]),
            "stale": len(due["stale"]),
        },
        "tags": tags,
        "next_tasks": next_tasks,
        "recent_tasks": tasks[:8],
        "due": due,
    }


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def due_buckets(tasks: list[dict[str, Any]] | None = None) -> dict[str, list[dict[str, Any]]]:
    tasks = tasks if tasks is not None else list_tasks()
    now = datetime.now(timezone.utc)
    buckets: dict[str, list[dict[str, Any]]] = {"overdue": [], "due_soon": [], "no_due_date": [], "stale": []}
    for task in tasks:
        if task["status"] == "done":
            continue
        due_date = _parse_iso(task.get("due_at"))
        if due_date is not None:
            if due_date < now:
                buckets["overdue"].append(task)
            elif (due_date - now).days <= 7:
                buckets["due_soon"].append(task)
        else:
            buckets["no_due_date"].append(task)
            created_date = _parse_iso(task.get("created_at"))
            if created_date is not None and (now - created_date).days >= 14:
                buckets["stale"].append(task)
    return buckets


def suggest_next_tasks(limit: int = 3) -> list[dict[str, Any]]:
    def score(task: dict[str, Any]) -> int:
        due_bonus = 15 if task.get("due_at") else 0
        tag_bonus = 3 * len(task.get("tags") or [])
        return due_bonus + tag_bonus

    tasks = [task for task in list_tasks() if task["status"] != "done"]
    return sorted(tasks, key=score, reverse=True)[:limit]


# ---------------------------------------------------------------------------
# AI draft pipeline
# ---------------------------------------------------------------------------


def _find_tag_id_by_title(title: str | None) -> str | None:
    if not title:
        return None
    normalized = title.strip().lower()
    for tag in list_tags():
        tag_name = tag["name"].lower()
        if normalized == tag_name or normalized in tag_name or tag_name in normalized:
            return tag["id"]
    return None


def _tag_context() -> str:
    tags = list_tags()
    if not tags:
        return "No tags exist yet. Use an empty tags list unless the command clearly names a topic."
    return "\n".join(f"- id={tag['id']} name={tag['name']}" for tag in tags)


def _extract_json_from_ollama(text: str) -> dict[str, Any] | None:
    prompt = f"""
You are Workmap's local planner parser. Return only valid JSON.

For create/add/make task commands:
- Extract the actual work item, not the command wrapper.
- Do not copy phrases like "create a task", "backlog task", "for me", "in tags", or "basically" into task titles or descriptions.
- Use concise verb-led titles such as "Watch YouTube video about laid-off ex-Atlassian employees".
- Descriptions should describe the work and next useful outcome, not repeat the user command.

Existing tags:
{_tag_context()}

Allowed action_type values:
- create_task
- update_task
- complete_task
- summarize
- suggest_next

For create_task return:
{{
  "action_type": "create_task",
  "payload": {{
    "title": "short polished task title, max 70 chars",
    "description": "clear 1-3 sentence task description",
    "status": "backlog",
    "due_at": null,
    "tags": ["short", "tags"]
  }}
}}

Rules:
- Do not copy the raw command as the title.
- Infer a concise title from the user's intent.
- Fill description and tags; prefer matching an existing tag name when clearly implied.
- New tasks always start in backlog.

Command: {text}
"""
    body = json.dumps({"model": OLLAMA_MODEL, "prompt": prompt, "stream": False, "format": "json"}).encode()
    request = urllib.request.Request(OLLAMA_URL, data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            raw = json.loads(response.read().decode())
        return json.loads(raw.get("response", "{}"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError):
        return None


def _strip_tag_and_date_phrases(value: str, tag_name: str | None) -> str:
    title = " ".join(value.replace("\n", " ").split())
    if tag_name:
        for phrase in (
            f"under {tag_name}",
            f"in {tag_name}",
            f"inside {tag_name}",
            f"for {tag_name}",
        ):
            title = title.replace(phrase, "")
            title = title.replace(phrase.title(), "")
    title = re.sub(
        r"\bunder\s+.+?\s+(?:to\s+)?(?=(study|read|prepare|plan|write|review|fix|build|learn|understand)\b)",
        "",
        title,
        flags=re.IGNORECASE,
    )
    lowered = title.lower()
    for marker in (" by next ", " before next ", " due next ", " by tomorrow", " by today", " due tomorrow", " due today"):
        idx = lowered.find(marker)
        if idx != -1:
            title = title[:idx]
            lowered = title.lower()
    for phrase in ("deeply", "properly", "in detail", "for interviews", "for interview", "for me"):
        title = title.replace(phrase, "").replace(phrase.title(), "")
    return " ".join(title.strip(" :-.").split())


def _looks_like_raw_command(candidate: str, original: str) -> bool:
    cleaned = candidate.strip().lower()
    source = original.strip().lower()
    if not cleaned:
        return True
    if cleaned == source:
        return True
    if len(candidate) > 72:
        return True
    command_fragments = (
        "create task",
        "add task",
        "under ",
        "inside ",
        "by next",
        "due next",
        "i need to",
        "i want to",
        "can you",
        "please",
    )
    return any(fragment in cleaned for fragment in command_fragments)


_TASK_COMMAND_PATTERNS = (
    r"^\s*(?:please\s+)?(?:create|add|make)\s+(?:a\s+|an\s+)?(?:new\s+)?(?:backlog\s+)?task(?:\s+(?:for\s+me|in\s+(?:the\s+)?tags?|to\s+(?:the\s+)?backlog))?\s*[:.\-]?\s*",
    r"^\s*(?:please\s+)?(?:create|add|make)\s+(?:this\s+)?(?:for\s+me\s+)?(?:in\s+(?:the\s+)?tags?)\s*[:.\-]?\s*",
)


def _strip_task_command_wrapper(value: str) -> str:
    cleaned = value.strip()
    previous = None
    while cleaned and cleaned != previous:
        previous = cleaned
        for pattern in _TASK_COMMAND_PATTERNS:
            cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"^\s*basically,?\s+(?:it\s+is\s+|it's\s+)?", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*(?:create|add|make)\s+the\s+task\s+for\s+me\s+in\s+(?:the\s+)?(?:goals?|tags?)\.?\s*$", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s+in\s+(?:the\s+)?(?:goals?|tags?)\.?\s*$", "", cleaned, flags=re.IGNORECASE)
        cleaned = cleaned.strip(" .:-")
    return cleaned


def _extract_task_intent_title(text: str) -> str | None:
    for part in re.split(r"(?<=[.!?])\s+", text):
        cleaned = _strip_task_command_wrapper(part)
        if not cleaned:
            continue
        if re.search(r"\b(?:create|add|make)\s+(?:a\s+|the\s+)?(?:backlog\s+)?task\b", cleaned, flags=re.IGNORECASE):
            continue
        lower = cleaned.lower()
        if lower.startswith(("watching ", "watch ")):
            cleaned = re.sub(r"^(?:it\s+is\s+|it's\s+)?watching\b", "Watch", cleaned, flags=re.IGNORECASE)
            cleaned = re.sub(r"^watch\b", "Watch", cleaned, flags=re.IGNORECASE)
            cleaned = re.sub(r"\b(?:a\s+)?youtube\s+of\b", "YouTube video about", cleaned, flags=re.IGNORECASE)
            return cleaned[:70].rstrip(" .:-")
        if lower.startswith(("study ", "read ", "review ", "prepare ", "build ", "update ", "fix ")):
            return cleaned[:70].rstrip(" .:-")
    cleaned = _strip_task_command_wrapper(text)
    if cleaned and len(cleaned.split()) >= 3:
        return cleaned[:70].rstrip(" .:-")
    return None


def _title_is_command_wrapper(candidate: str, original: str) -> bool:
    lowered = candidate.strip().lower()
    if _looks_like_raw_command(candidate, original):
        return True
    if lowered.startswith(("create ", "add ", "make ")) and len(lowered.split()) <= 4:
        return True
    return bool(
        re.search(r"\b(?:create|add|make)\s+(?:a\s+|the\s+)?(?:backlog\s+)?task\b", lowered)
        or lowered.startswith("basically")
    )


def _description_from_title(title: str, task_type: str) -> str:
    subject = title.strip().rstrip(".")
    if not subject:
        return ""
    if task_type == "study":
        match = re.match(r"watch\s+youtube\s+video\s+about\s+(.+)", subject, flags=re.IGNORECASE)
        if match:
            return f"Watch the YouTube video about {match.group(1)}. Capture key takeaways and any follow-up action."
        return f"{subject}. Capture key takeaways and any follow-up action."
    return subject


def _description_is_command_wrapper(candidate: str, original: str) -> bool:
    lowered = candidate.strip().lower()
    return bool(
        lowered.startswith("work on:")
        or re.search(r"\b(?:create|add|make)\s+(?:a\s+|the\s+)?(?:backlog\s+)?task\b", lowered)
        or "basically" in lowered
        or lowered == original.strip().lower()
    )


def _clean_task_description(text: str, candidate: str | None, title: str, task_type: str) -> str:
    description = (candidate or "").strip()
    if description and not _description_is_command_wrapper(description, text):
        return description
    return _description_from_title(title, task_type) or description


def _clean_task_type(text: str, candidate: str | None, fallback: str) -> str:
    lowered = text.lower()
    if any(word in lowered for word in ("watch", "youtube", "study", "learn", "read")):
        return "study"
    return candidate or fallback


def _clean_task_title(text: str, candidate: str | None, tag_name: str | None = None) -> str:
    source = candidate or text
    extracted = _extract_task_intent_title(text)
    if extracted and (not candidate or _title_is_command_wrapper(candidate, text)):
        return extracted

    if candidate and _looks_like_raw_command(candidate, text):
        source = text
    title = source.strip()
    lower = title.lower()
    for prefix in (
        "create a task to",
        "create task to",
        "create a task",
        "create task",
        "add a task to",
        "add task to",
        "add a task",
        "add task",
        "i need to",
        "i want to",
        "please",
    ):
        if lower.startswith(prefix):
            title = title[len(prefix):].strip(" :-")
            lower = title.lower()
            break
    title = _strip_tag_and_date_phrases(title, tag_name)
    lower = title.lower()

    if "difference between" in lower:
        topic = title[lower.find("difference between") + len("difference between"):].strip(" :-")
        topic = topic.replace(" and ", " vs ")
        title = f"Study {topic}"
    elif "payment system design" in lower:
        title = "Study payment system design" if any(word in lower for word in ("study", "understand", "learn")) else "Prepare payment system design"
    elif "next sprint" in lower:
        title = "Plan next sprint"
    elif lower.startswith(("understand ", "learn ", "read ", "revise ", "practice ")):
        verb, rest = title.split(" ", 1)
        title = f"Study {rest}" if verb.lower() in {"understand", "learn", "read", "revise"} else title
    elif not lower.startswith(("study ", "prepare ", "plan ", "write ", "review ", "fix ", "build ", "create ")):
        title = f"Study {title}" if any(word in lower for word in ("redis", "system design", "database", "kafka")) else title

    title = " ".join(title.strip(" :-.").split())
    if len(title) > 70:
        title = title[:67].rstrip() + "..."
    return title[:1].upper() + title[1:] if title else "Untitled task"


def _best_tag_name_hint(tags: list[str] | None) -> str | None:
    for tag in tags or []:
        if tag and tag != "ai-draft":
            return tag
    return None


def _infer_task_payload(text: str, context: dict[str, Any]) -> dict[str, Any]:
    cleaned = text.strip()
    lower = cleaned.lower()
    for prefix in ("create task", "add task", "task:"):
        if lower.startswith(prefix):
            cleaned = cleaned[len(prefix):].strip(" :-")
            lower = cleaned.lower()
            break

    tag_name_hint = None
    for tag in list_tags():
        tag_name = tag["name"]
        if tag_name.lower() in lower:
            tag_name_hint = tag_name
            cleaned = cleaned.replace(tag_name, "").strip(" :-")
            break

    title = _clean_task_title(text, cleaned, tag_name_hint)
    description = (
        f"Work on: {cleaned}. Capture notes and the next useful action."
        if cleaned
        else "Task created from planner input. Add description before starting."
    )
    tags: list[str] = []
    for word in ("redis", "payment", "system-design", "sprint", "interview", "database", "kafka"):
        if word.replace("-", " ") in lower or word in lower:
            tags.append(word)
    if tag_name_hint:
        tags.append(tag_name_hint)

    return {
        "title": title,
        "description": description,
        "status": "backlog",
        "due_at": None,
        "tags": tags or ["ai-draft"],
    }


def _normalize_task_payload(payload: dict[str, Any], text: str, context: dict[str, Any]) -> dict[str, Any]:
    fallback = _infer_task_payload(text, context)
    payload_tags = payload.get("tags") or fallback["tags"]
    tag_name_hint = _best_tag_name_hint(payload_tags)
    title = _clean_task_title(text, payload.get("title") or fallback["title"], tag_name_hint)
    task_type_hint = _clean_task_type(text, payload.get("type"), "task")
    return {
        "title": title,
        "description": _clean_task_description(
            text,
            payload.get("description") or fallback["description"],
            title,
            task_type_hint,
        ),
        "status": "backlog",
        "due_at": payload.get("due_at") or fallback.get("due_at"),
        "tags": payload_tags,
    }


def create_ai_draft(input_text: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
    context = context or {}
    text = input_text.strip()
    lower = text.lower()
    parsed = _extract_json_from_ollama(text) or {}
    action_type = parsed.get("action_type")
    payload = parsed.get("payload") or {}

    if "what can you do" in lower or "capabilities" in lower:
        action_type = "summarize"
        payload = {"summary": planner_capabilities()}
    elif any(phrase in lower for phrase in ("what should", "pick next", "study next", "next task")):
        action_type = "suggest_next"
        payload = {"tasks": suggest_next_tasks(3)}
    elif "summar" in lower:
        action_type = "summarize"
        payload = {"summary": summarize_workspace()}
    elif "complete" in lower:
        action_type = "complete_task"
        payload = {"task_id": context.get("task_id")}
    elif not action_type:
        action_type = "create_task"
        payload = _infer_task_payload(text, context)

    if action_type == "create_task":
        payload = _normalize_task_payload(payload, text, context)
    elif action_type == "suggest_next":
        payload = {"tasks": suggest_next_tasks(3)}
    elif action_type == "summarize":
        payload = {"summary": payload.get("summary") or summarize_workspace()}

    draft_id = _id("draft")
    now = _now()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO llm_action_drafts (id, action_type, input_text, proposed_payload_json, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (draft_id, action_type, input_text, json.dumps(payload), "pending", now),
        )
    return {"id": draft_id, "action_type": action_type, "input_text": input_text, "payload": payload, "status": "pending"}


def confirm_ai_draft(draft_id: str, overrides: dict[str, Any] | None = None) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM llm_action_drafts WHERE id = ?", (draft_id,)).fetchone()
        if row is None:
            return None
        action_type = row["action_type"]
        payload = json.loads(row["proposed_payload_json"])
        if overrides:
            payload.update({key: value for key, value in overrides.items() if value is not None})
        conn.execute(
            "UPDATE llm_action_drafts SET status = ?, confirmed_at = ? WHERE id = ?",
            ("confirmed", _now(), draft_id),
        )
    if action_type == "create_task":
        tags = payload.pop("tags", None)
        if tags:
            payload.setdefault("tag_names", tags)
        result = create_task(payload)
    elif action_type == "complete_task" and payload.get("task_id"):
        result = complete_task(payload["task_id"]) or {}
    else:
        result = payload
    return {"id": draft_id, "action_type": action_type, "status": "confirmed", "result": result}


def planner_capabilities() -> str:
    return (
        "I can create backlog tasks, tag them, complete tasks, suggest what to pick next, "
        "summarize the planner, and prepare due-date changes. "
        "Mutating actions are shown as drafts before confirmation."
    )


def summarize_workspace() -> str:
    tags = list_tags()
    tasks = list_tasks()
    open_tasks = [task for task in tasks if task["status"] != "done"]
    due = due_buckets(tasks)
    return (
        f"{len(tags)} tags, {len(open_tasks)} open tasks. "
        f"{len(due['due_soon'])} due soon, {len(due['overdue'])} overdue, {len(due['stale'])} stale. "
        "Use due dates and tags instead of day-only planning."
    )
