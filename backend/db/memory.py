"""
Supabase-backed conversation persistence for the akash-planner agent.

Provides load/save helpers that convert between LangChain message objects
and rows in the `conversations` table, enabling cross-session memory that
survives server restarts.

Table schema expected:
    thread_id   text
    role        text  (user | assistant | tool)
    content     text
    tool_calls  jsonb (nullable)
    tool_call_id text (nullable)
    tool_name   text (nullable)
    created_at  timestamptz (auto)

Public API:
    load_conversation(thread_id) -> list of LangChain message objects
    save_messages(thread_id, messages) -> None
"""

import json

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from db.supabase_client import get_supabase


def load_conversation(thread_id: str, last_n: int = 6) -> list:
    """Load the most recent messages for a thread from Supabase, oldest-first.

    Limits to last_n messages to keep token usage bounded — full history
    grows unbounded and will exceed model TPM/TPD limits.

    Args:
        thread_id: The session identifier used when the messages were saved.
        last_n:    Max messages to load (default 20, ~2-3 conversation turns).

    Returns:
        List of LangChain message objects in chronological order.
        Returns an empty list if the thread has no history or on error.
    """
    db = get_supabase()
    try:
        result = (
            db.table("conversations")
            .select("*")
            .eq("thread_id", thread_id)
            .order("created_at", desc=True)
            .limit(last_n)
            .execute()
        )
        # Results came back newest-first; reverse to get chronological order
        if result.data:
            result.data.reverse()
        rows = result.data or []
    except Exception:
        return []

    messages: list = []
    for row in rows:
        role = row.get("role", "")
        content = row.get("content", "")

        if role == "user":
            messages.append(HumanMessage(content=content))

        elif role == "assistant":
            raw_tool_calls = row.get("tool_calls")
            if raw_tool_calls:
                # tool_calls stored as JSON list
                tool_calls = (
                    raw_tool_calls
                    if isinstance(raw_tool_calls, list)
                    else json.loads(raw_tool_calls)
                )
                messages.append(AIMessage(content=content, tool_calls=tool_calls))
            else:
                messages.append(AIMessage(content=content))

        elif role == "tool":
            tool_call_id = row.get("tool_call_id", "")
            tool_name = row.get("tool_name", "")
            messages.append(
                ToolMessage(
                    content=content,
                    tool_call_id=tool_call_id,
                    name=tool_name,
                )
            )

    return messages


def save_messages(thread_id: str, messages: list) -> None:
    """Persist a list of LangChain messages to the conversations table.

    Converts each message to a row dict and inserts. Uses upsert with
    on_conflict=ignore semantics via a pre-check: loads the existing row
    count for the thread first and only inserts messages beyond that count.
    This avoids duplicating messages across multiple save calls while keeping
    the implementation simple (no per-message hash column required).

    Args:
        thread_id: Session identifier to group messages under.
        messages:  Ordered list of LangChain message objects to persist.
                   Typically the full state["messages"] from the agent run.
    """
    if not messages:
        return

    db = get_supabase()

    # Determine how many rows already exist for this thread
    try:
        existing = (
            db.table("conversations")
            .select("id", count="exact")
            .eq("thread_id", thread_id)
            .execute()
        )
        already_saved = existing.count or 0
    except Exception:
        already_saved = 0

    # Only persist messages beyond what's already in the database
    new_messages = messages[already_saved:]
    if not new_messages:
        return

    rows: list[dict] = []
    for msg in new_messages:
        if isinstance(msg, HumanMessage):
            rows.append(
                {
                    "thread_id": thread_id,
                    "role": "user",
                    "content": msg.content if isinstance(msg.content, str) else str(msg.content),
                }
            )

        elif isinstance(msg, AIMessage):
            # Only save the final answer — discard intermediate steps that have tool_calls
            if msg.tool_calls:
                continue
            rows.append(
                {
                    "thread_id": thread_id,
                    "role": "assistant",
                    "content": msg.content if isinstance(msg.content, str) else str(msg.content),
                }
            )

        # ToolMessage rows (observations) are intentionally discarded

    if rows:
        try:
            db.table("conversations").insert(rows).execute()
        except Exception as e:
            # Non-fatal — in-session memory still works via MemorySaver
            print(f"[memory] Warning: failed to save {len(rows)} message(s): {e}")
