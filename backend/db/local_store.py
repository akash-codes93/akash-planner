from __future__ import annotations

import json
import os
import sqlite3
import urllib.error
import urllib.request
from contextlib import contextmanager
from datetime import datetime, timezone
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


def _json_loads(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    data = dict(row)
    if "tags_json" in data:
        data["tags"] = _json_loads(data.pop("tags_json"), [])
    if "payload_json" in data:
        data["payload"] = _json_loads(data.pop("payload_json"), {})
    if "proposed_payload_json" in data:
        data["payload"] = _json_loads(data.pop("proposed_payload_json"), {})
    return data


def _rows_to_dicts(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    return [item for row in rows if (item := _row_to_dict(row)) is not None]


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


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
                goal_id TEXT REFERENCES goals(id) ON DELETE SET NULL,
                title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'backlog',
                type TEXT NOT NULL DEFAULT 'task',
                priority INTEGER NOT NULL DEFAULT 50,
                estimate_minutes INTEGER NOT NULL DEFAULT 30,
                logged_minutes INTEGER NOT NULL DEFAULT 0,
                progress_percent INTEGER NOT NULL DEFAULT 0,
                due_at TEXT,
                planned_start_at TEXT,
                last_worked_at TEXT,
                completed_at TEXT,
                archived_at TEXT,
                tags_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS focus_sessions (
                id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                started_at TEXT NOT NULL,
                ended_at TEXT,
                duration_minutes INTEGER NOT NULL DEFAULT 0,
                progress_delta INTEGER NOT NULL DEFAULT 0,
                summary TEXT NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS task_events (
                id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                event_type TEXT NOT NULL,
                payload_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
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
            """
        )
        _ensure_column(conn, "tasks", "logged_minutes", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "tasks", "planned_start_at", "TEXT")
        _ensure_column(conn, "tasks", "last_worked_at", "TEXT")
        _ensure_column(conn, "tasks", "completed_at", "TEXT")
        _ensure_column(conn, "tasks", "archived_at", "TEXT")
        _ensure_column(conn, "llm_action_drafts", "confirmed_at", "TEXT")
        count = conn.execute("SELECT COUNT(*) AS count FROM goals").fetchone()["count"]
        seed_disabled = conn.execute(
            "SELECT value FROM app_settings WHERE key = ?",
            ("seed_disabled",),
        ).fetchone()
        if count == 0 and not seed_disabled:
            seed(conn)


def seed(conn: sqlite3.Connection) -> None:
    now = _now()
    goals = [
        ("goal-career", "Switch job preparation", "Interview preparation and system design depth.", "active", 90, 40),
        ("goal-work", "Company execution", "Current and upcoming sprint execution.", "active", 80, 20),
        ("goal-learning", "Core engineering depth", "Small learning tasks and engineering fundamentals.", "active", 70, 0),
    ]
    conn.executemany(
        """
        INSERT INTO goals (id, title, description, status, priority, progress_percent, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [(*goal, now, now) for goal in goals],
    )

    tasks = [
        (
            "task-payments",
            "goal-career",
            "Prepare payment system design",
            "Cover lifecycle, idempotency, ledger, reconciliation, retries, and failure handling.",
            "doing",
            "study",
            91,
            360,
            0,
            40,
            None,
            None,
            now,
            None,
            None,
            ["system-design", "interview"],
        ),
        (
            "task-redis",
            "goal-learning",
            "Study Redis set vs sorted set",
            "Understand operations, use cases, and tradeoffs.",
            "backlog",
            "study",
            74,
            25,
            0,
            0,
            None,
            None,
            None,
            None,
            None,
            ["redis", "quick-win"],
        ),
        (
            "task-sprint",
            "goal-work",
            "Plan next sprint execution",
            "Group tasks into must-ship, risk, and follow-up.",
            "backlog",
            "company",
            82,
            90,
            0,
            15,
            None,
            None,
            now,
            None,
            None,
            ["sprint"],
        ),
        (
            "task-observability",
            "goal-work",
            "Design API latency dashboard",
            "Define metrics, panels, and alert thresholds.",
            "blocked",
            "company",
            67,
            180,
            0,
            10,
            None,
            None,
            now,
            None,
            None,
            ["observability"],
        ),
        (
            "task-kafka",
            "goal-career",
            "Deep dive Kafka consumer rebalancing",
            "Study assignment strategies and failure behavior.",
            "backlog",
            "study",
            52,
            120,
            0,
            0,
            None,
            None,
            None,
            None,
            None,
            ["distributed-systems"],
        ),
    ]
    conn.executemany(
        """
        INSERT INTO tasks (
            id, goal_id, title, description, status, type, priority, estimate_minutes,
            logged_minutes, progress_percent, due_at, planned_start_at, last_worked_at,
            completed_at, archived_at, tags_json, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [(*task[:15], json.dumps(task[15]), now, now) for task in tasks],
    )

    sessions = [
        ("session-payments-1", "task-payments", now, now, 55, 20, "Read payment lifecycle and gateway flow."),
        ("session-payments-2", "task-payments", now, now, 85, 20, "Added notes from this focus session."),
        ("session-sprint-1", "task-sprint", now, now, 20, 15, "Collected open sprint threads."),
    ]
    conn.executemany(
        """
        INSERT INTO focus_sessions (id, task_id, started_at, ended_at, duration_minutes, progress_delta, summary)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        sessions,
    )


def list_goals() -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT
                g.*,
                COUNT(t.id) AS task_count,
                COALESCE(ROUND(AVG(t.progress_percent)), g.progress_percent) AS calculated_progress
            FROM goals g
            LEFT JOIN tasks t ON t.goal_id = g.id AND t.archived_at IS NULL
            GROUP BY g.id
            ORDER BY g.priority DESC, g.created_at DESC
            """
        ).fetchall()
        return _rows_to_dicts(rows)


def get_goal(goal_id: str) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM goals WHERE id = ?", (goal_id,)).fetchone()
        return _row_to_dict(row)


def create_goal(payload: dict[str, Any]) -> dict[str, Any]:
    goal_id = payload.get("id") or _id("goal")
    now = _now()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO goals (id, title, description, status, priority, progress_percent, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                goal_id,
                payload["title"],
                payload.get("description", ""),
                payload.get("status", "active"),
                payload.get("priority", 50),
                payload.get("progress_percent", 0),
                now,
                now,
            ),
        )
    return get_goal(goal_id) or {}


def update_goal(goal_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    allowed = {"title", "description", "status", "priority", "progress_percent"}
    updates = {key: value for key, value in payload.items() if key in allowed and value is not None}
    if not updates:
        return get_goal(goal_id)
    assignments = ", ".join(f"{key} = ?" for key in updates)
    values = list(updates.values()) + [_now(), goal_id]
    with _connect() as conn:
        conn.execute(f"UPDATE goals SET {assignments}, updated_at = ? WHERE id = ?", values)
    return get_goal(goal_id)


def _task_where(goal_id: str | None, status: str | None, include_archived: bool) -> tuple[str, list[Any]]:
    where = []
    params: list[Any] = []
    if not include_archived:
        where.append("t.archived_at IS NULL")
    if goal_id:
        where.append("t.goal_id = ?")
        params.append(goal_id)
    if status:
        where.append("t.status = ?")
        params.append(status)
    return (f"WHERE {' AND '.join(where)}" if where else "", params)


def list_tasks(
    goal_id: str | None = None,
    status: str | None = None,
    include_archived: bool = False,
) -> list[dict[str, Any]]:
    where_clause, params = _task_where(goal_id, status, include_archived)
    with _connect() as conn:
        rows = conn.execute(
            f"""
            SELECT
                t.*,
                g.title AS goal_title,
                COALESCE(SUM(f.duration_minutes), 0) AS session_minutes,
                (t.logged_minutes + COALESCE(SUM(f.duration_minutes), 0)) AS total_logged_minutes
            FROM tasks t
            LEFT JOIN goals g ON g.id = t.goal_id
            LEFT JOIN focus_sessions f ON f.task_id = t.id
            {where_clause}
            GROUP BY t.id
            ORDER BY
                CASE t.status
                    WHEN 'doing' THEN 0
                    WHEN 'next' THEN 1
                    WHEN 'backlog' THEN 2
                    WHEN 'blocked' THEN 3
                    WHEN 'done' THEN 4
                    ELSE 5
                END,
                CASE WHEN t.due_at IS NULL THEN 1 ELSE 0 END,
                t.due_at ASC,
                t.priority DESC,
                t.created_at DESC
            """,
            params,
        ).fetchall()
        return _rows_to_dicts(rows)


def get_task(task_id: str) -> dict[str, Any] | None:
    with _connect() as conn:
        task = conn.execute(
            """
            SELECT
                t.*,
                g.title AS goal_title,
                COALESCE(SUM(f.duration_minutes), 0) AS session_minutes,
                (t.logged_minutes + COALESCE(SUM(f.duration_minutes), 0)) AS total_logged_minutes
            FROM tasks t
            LEFT JOIN goals g ON g.id = t.goal_id
            LEFT JOIN focus_sessions f ON f.task_id = t.id
            WHERE t.id = ?
            GROUP BY t.id
            """,
            (task_id,),
        ).fetchone()
        data = _row_to_dict(task)
        if data is None:
            return None
        sessions = conn.execute(
            "SELECT * FROM focus_sessions WHERE task_id = ? ORDER BY started_at DESC",
            (task_id,),
        ).fetchall()
        events = conn.execute(
            "SELECT id, event_type, payload_json, created_at FROM task_events WHERE task_id = ? ORDER BY created_at DESC",
            (task_id,),
        ).fetchall()
        data["sessions"] = _rows_to_dicts(sessions)
        data["events"] = _rows_to_dicts(events)
        return data


def create_task(payload: dict[str, Any]) -> dict[str, Any]:
    task_id = payload.get("id") or _id("task")
    now = _now()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO tasks (
                id, goal_id, title, description, status, type, priority, estimate_minutes,
                logged_minutes, progress_percent, due_at, planned_start_at, last_worked_at,
                completed_at, archived_at, tags_json, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task_id,
                payload.get("goal_id"),
                payload["title"],
                payload.get("description", ""),
                payload.get("status", "backlog"),
                payload.get("type", "task"),
                payload.get("priority", 50),
                payload.get("estimate_minutes", 30),
                payload.get("logged_minutes", 0),
                payload.get("progress_percent", 0),
                payload.get("due_at"),
                payload.get("planned_start_at"),
                payload.get("last_worked_at"),
                payload.get("completed_at"),
                payload.get("archived_at"),
                json.dumps(payload.get("tags", [])),
                now,
                now,
            ),
        )
    return get_task(task_id) or {}


def update_task(task_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    allowed = {
        "goal_id",
        "title",
        "description",
        "status",
        "type",
        "priority",
        "estimate_minutes",
        "logged_minutes",
        "progress_percent",
        "due_at",
        "planned_start_at",
        "last_worked_at",
        "completed_at",
        "archived_at",
    }
    updates = {key: value for key, value in payload.items() if key in allowed}
    if "tags" in payload:
        updates["tags_json"] = json.dumps(payload["tags"] or [])
    if updates.get("status") == "done":
        updates.setdefault("progress_percent", 100)
        updates.setdefault("completed_at", _now())
    if not updates:
        return get_task(task_id)
    assignments = ", ".join(f"{key} = ?" for key in updates)
    values = list(updates.values()) + [_now(), task_id]
    with _connect() as conn:
        conn.execute(f"UPDATE tasks SET {assignments}, updated_at = ? WHERE id = ?", values)
    return get_task(task_id)


def add_progress(task_id: str, progress_delta: int, minutes: int, summary: str) -> dict[str, Any] | None:
    task = get_task(task_id)
    if task is None:
        return None
    next_progress = min(100, max(0, int(task["progress_percent"]) + progress_delta))
    status = "done" if next_progress >= 100 else "doing"
    now = _now()
    clean_summary = summary.strip() or f"Added {progress_delta}% progress."
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO focus_sessions (id, task_id, started_at, ended_at, duration_minutes, progress_delta, summary)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (_id("session"), task_id, now, now, minutes, progress_delta, clean_summary),
        )
        conn.execute(
            """
            UPDATE tasks
            SET progress_percent = ?, status = ?, last_worked_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (next_progress, status, now, now, task_id),
        )
        conn.execute(
            """
            INSERT INTO task_events (id, task_id, event_type, payload_json, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                _id("event"),
                task_id,
                "progress_added",
                json.dumps({"progress_delta": progress_delta, "minutes": minutes, "summary": clean_summary}),
                now,
            ),
        )
    return get_task(task_id)


def complete_task(task_id: str) -> dict[str, Any] | None:
    return update_task(task_id, {"status": "done", "progress_percent": 100, "completed_at": _now()})


def archive_task(task_id: str) -> dict[str, Any] | None:
    return update_task(task_id, {"archived_at": _now()})


def delete_task(task_id: str) -> bool:
    with _connect() as conn:
        cursor = conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        return cursor.rowcount > 0


def clear_workspace() -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM llm_action_drafts")
        conn.execute("DELETE FROM task_events")
        conn.execute("DELETE FROM focus_sessions")
        conn.execute("DELETE FROM tasks")
        conn.execute("DELETE FROM goals")
        conn.execute(
            "INSERT OR REPLACE INTO app_settings (key, value) VALUES (?, ?)",
            ("seed_disabled", "true"),
        )


def dashboard() -> dict[str, Any]:
    goals = list_goals()
    tasks = list_tasks()
    active_tasks = [task for task in tasks if task["status"] != "done"]
    blocked_tasks = [task for task in tasks if task["status"] == "blocked"]
    logged_minutes = sum(int(task.get("total_logged_minutes") or 0) for task in tasks)
    next_tasks = suggest_next_tasks(5)
    due = due_buckets(tasks)
    return {
        "stats": {
            "goals": len(goals),
            "active_tasks": len(active_tasks),
            "blocked_tasks": len(blocked_tasks),
            "logged_minutes": logged_minutes,
            "due_soon": len(due["due_soon"]),
            "overdue": len(due["overdue"]),
            "stale": len(due["stale"]),
        },
        "goals": goals,
        "next_tasks": next_tasks,
        "recent_tasks": tasks[:8],
        "due": due,
    }


def due_buckets(tasks: list[dict[str, Any]] | None = None) -> dict[str, list[dict[str, Any]]]:
    tasks = tasks or list_tasks()
    now = datetime.now(timezone.utc)
    buckets = {"overdue": [], "due_soon": [], "no_due_date": [], "stale": []}
    for task in tasks:
        if task["status"] == "done":
            continue
        due_at = task.get("due_at")
        if due_at:
            try:
                due_date = datetime.fromisoformat(due_at.replace("Z", "+00:00"))
                days = (due_date - now).days
                if due_date < now:
                    buckets["overdue"].append(task)
                elif days <= 7:
                    buckets["due_soon"].append(task)
            except ValueError:
                buckets["no_due_date"].append(task)
        else:
            buckets["no_due_date"].append(task)
        if int(task.get("progress_percent") or 0) > 0 and task.get("last_worked_at") is None:
            buckets["stale"].append(task)
    return buckets


def suggest_next_tasks(limit: int = 3) -> list[dict[str, Any]]:
    def score(task: dict[str, Any]) -> int:
        status_bonus = {"doing": 25, "next": 18, "backlog": 5, "blocked": -40, "done": -100}.get(task["status"], 0)
        progress_bonus = 12 if 0 < int(task["progress_percent"]) < 100 else 0
        quick_win_bonus = 10 if int(task["estimate_minutes"]) <= 30 else 0
        due_bonus = 15 if task.get("due_at") else 0
        return int(task["priority"]) + status_bonus + progress_bonus + quick_win_bonus + due_bonus

    tasks = [task for task in list_tasks() if task["status"] != "done"]
    return sorted(tasks, key=score, reverse=True)[:limit]


def _find_goal_id_by_title(title: str | None) -> str | None:
    if not title:
        return None
    normalized = title.strip().lower()
    for goal in list_goals():
        goal_title = goal["title"].lower()
        if normalized == goal_title or normalized in goal_title or goal_title in normalized:
            return goal["id"]
    return None


def _goal_context() -> str:
    goals = list_goals()
    if not goals:
        return "No goals exist yet. Use null goal_id unless the command asks to create a goal."
    return "\n".join(f"- id={goal['id']} title={goal['title']}" for goal in goals)


def _extract_json_from_ollama(text: str) -> dict[str, Any] | None:
    prompt = f"""
You are Workmap's local planner parser. Return only valid JSON.

Existing goals:
{_goal_context()}

Allowed action_type values:
- create_task
- create_goal
- update_task
- complete_task
- summarize
- suggest_next

For create_task return:
{{
  "action_type": "create_task",
  "payload": {{
    "title": "short polished task title, max 70 chars",
    "goal_id": "one existing goal id if clearly matched, else null",
    "goal_title": "matched goal title or null",
    "description": "clear 1-3 sentence task description",
    "status": "backlog",
    "type": "study|company|task|project",
    "priority": integer 0-100,
    "estimate_minutes": integer,
    "due_at": null,
    "tags": ["short", "tags"]
  }}
}}

Rules:
- Do not copy the raw command as the title.
- Infer a concise title from the user's intent.
- Fill description, priority, estimate_minutes, type, and tags.
- Pick goal_id only from the existing goal list.
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


def _infer_task_payload(text: str, context: dict[str, Any]) -> dict[str, Any]:
    cleaned = text.strip()
    lower = cleaned.lower()
    for prefix in ("create task", "add task", "task:"):
        if lower.startswith(prefix):
            cleaned = cleaned[len(prefix):].strip(" :-")
            lower = cleaned.lower()
            break

    goal_id = context.get("goal_id")
    if not goal_id:
        for goal in list_goals():
            goal_title = goal["title"]
            if goal_title.lower() in lower:
                goal_id = goal["id"]
                cleaned = cleaned.replace(goal_title, "").strip(" :-")
                break

    task_type = "study" if any(word in lower for word in ("study", "read", "learn", "revise", "practice")) else "task"
    if any(word in lower for word in ("sprint", "company", "ticket", "prod", "release")):
        task_type = "company"
    if any(word in lower for word in ("design", "system", "architecture", "project")):
        task_type = "project" if task_type != "company" else "company"

    estimate = 30
    priority = 50
    if any(word in lower for word in ("system design", "architecture", "project", "payment")):
        estimate = 180
        priority = 82
    if any(word in lower for word in ("urgent", "blocked", "deadline", "interview")):
        priority = 90
    if any(word in lower for word in ("quick", "small", "minor", "difference between")):
        estimate = 25
        priority = max(priority, 65)

    title = cleaned[:70].strip() or "Untitled task"
    title = title[0].upper() + title[1:] if title else title
    description = (
        f"Work on: {cleaned}. Capture notes, progress, and next action when the focus session ends."
        if cleaned
        else "Task created from planner input. Add description before starting."
    )
    tags = []
    for word in ("redis", "payment", "system-design", "sprint", "interview", "database", "kafka"):
        if word.replace("-", " ") in lower or word in lower:
            tags.append(word)

    return {
        "title": title,
        "goal_id": goal_id,
        "description": description,
        "status": "backlog",
        "type": task_type,
        "priority": priority,
        "estimate_minutes": estimate,
        "due_at": None,
        "tags": tags or ["ai-draft"],
    }


def _normalize_task_payload(payload: dict[str, Any], text: str, context: dict[str, Any]) -> dict[str, Any]:
    fallback = _infer_task_payload(text, context)
    goal_id = payload.get("goal_id") or context.get("goal_id") or _find_goal_id_by_title(payload.get("goal_title"))
    return {
        "title": (payload.get("title") or fallback["title"])[:90],
        "goal_id": goal_id or fallback.get("goal_id"),
        "description": payload.get("description") or fallback["description"],
        "status": "backlog",
        "type": payload.get("type") or fallback["type"],
        "priority": int(payload.get("priority") or fallback["priority"]),
        "estimate_minutes": int(payload.get("estimate_minutes") or fallback["estimate_minutes"]),
        "due_at": payload.get("due_at") or fallback.get("due_at"),
        "tags": payload.get("tags") or fallback["tags"],
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
    elif "create goal" in lower or lower.startswith("goal "):
        action_type = "create_goal"
        title = text.replace("create goal", "", 1).replace("Goal", "", 1).strip(" :-") or payload.get("title") or "Untitled goal"
        payload = {
            "title": payload.get("title") or title,
            "description": payload.get("description") or "Goal created from planner input.",
            "priority": int(payload.get("priority") or 50),
        }
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
    if action_type == "create_goal":
        result = create_goal(payload)
    elif action_type == "create_task":
        result = create_task(payload)
    elif action_type == "complete_task" and payload.get("task_id"):
        result = complete_task(payload["task_id"]) or {}
    else:
        result = payload
    return {"id": draft_id, "action_type": action_type, "status": "confirmed", "result": result}


def planner_capabilities() -> str:
    return (
        "I can draft goals, create backlog tasks, add tasks inside the current goal, complete tasks, "
        "suggest what to pick next, summarize the planner, and prepare due-date or priority changes. "
        "Mutating actions are shown as drafts before confirmation."
    )


def summarize_workspace() -> str:
    goals = list_goals()
    tasks = list_tasks()
    doing = [task for task in tasks if task["status"] == "doing"]
    blocked = [task for task in tasks if task["status"] == "blocked"]
    due = due_buckets(tasks)
    return (
        f"{len(goals)} goals, {len(tasks)} active tasks. "
        f"{len(doing)} in progress, {len(blocked)} blocked, "
        f"{len(due['due_soon'])} due soon, {len(due['stale'])} stale. "
        "Use due dates and progress notes instead of day-only planning."
    )
