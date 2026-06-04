"""
FastAPI server for the akash-planner backend.

Endpoints:
    POST /chat   — run the ReAct agent, returns structured steps + final answer
    GET  /items  — direct Supabase query for fast dashboard reads (bypasses agent)
    GET  /health — liveness check

Run with:
    cd backend
    uvicorn api.server:app --reload --port 8000

The agent instance is created once at startup and reused across requests.
Thread-level memory is keyed by the thread_id in the request body.
"""

import json
import os
from contextlib import asynccontextmanager
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from pydantic import BaseModel

from agent.graph import build_agent, run_with_memory
from db.supabase_client import get_supabase

load_dotenv()

# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class ChatRequest(BaseModel):
    message: str
    thread_id: str = "default"


class StepOut(BaseModel):
    type: str          # "thought" | "action" | "observation" | "answer"
    content: str
    tool_name: str | None = None
    tool_input: dict | None = None


class ChatResponse(BaseModel):
    steps: list[StepOut]
    answer: str


# ---------------------------------------------------------------------------
# App lifecycle
# ---------------------------------------------------------------------------

_agent = None  # module-level singleton


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Build the agent once at startup."""
    global _agent
    _agent = build_agent()
    yield


app = FastAPI(
    title="Akash Planner API",
    description="ReAct agent backend for personal productivity management.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/health")
async def health() -> dict[str, str]:
    """Liveness check — returns immediately without hitting any external service."""
    return {"status": "ok"}


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    """Run the ReAct agent and return all intermediate steps plus the final answer.

    The response includes every Thought, Action, and Observation so the
    frontend can render the reasoning loop visually.

    Request body:
        message:   The user's message.
        thread_id: Session identifier for multi-turn memory. Use the same
                   thread_id across requests to maintain conversation context.

    Response:
        steps:  List of reasoning steps, each with type, content, and optional
                tool_name / tool_input for action steps.
        answer: The agent's final plain-text response.
    """
    if _agent is None:
        raise HTTPException(status_code=503, detail="Agent not initialized.")

    steps: list[StepOut] = []
    answer = ""

    try:
        for event in run_with_memory(_agent, request.message, thread_id=request.thread_id):
            messages = event.get("messages", [])
            if not messages:
                continue

            last = messages[-1]

            if isinstance(last, AIMessage):
                # Extract text content
                text = ""
                if isinstance(last.content, str):
                    text = last.content.strip()
                elif isinstance(last.content, list):
                    text = " ".join(
                        block.get("text", "") if isinstance(block, dict) else str(block)
                        for block in last.content
                    ).strip()

                if last.tool_calls:
                    if text:
                        steps.append(StepOut(type="thought", content=text))
                    for tc in last.tool_calls:
                        steps.append(
                            StepOut(
                                type="action",
                                content=f"Calling {tc['name']}",
                                tool_name=tc["name"],
                                tool_input=tc.get("args", {}),
                            )
                        )
                else:
                    if text:
                        answer = text
                        steps.append(StepOut(type="answer", content=text))

            elif isinstance(last, ToolMessage):
                content = last.content or ""
                name = getattr(last, "name", "") or ""
                steps.append(
                    StepOut(
                        type="observation",
                        content=content,
                        tool_name=name,
                    )
                )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Agent error: {e}")

    return ChatResponse(steps=steps, answer=answer)


@app.get("/items")
async def list_items(
    category: str | None = Query(default=None),
    status: str | None = Query(default=None),
    item_type: str | None = Query(default=None),
    sort_by: str = Query(default="priority"),
    limit: int = Query(default=20, ge=1, le=200),
) -> dict[str, Any]:
    """Directly query Supabase items — bypasses the agent for fast reads.

    Useful for dashboard views that need raw item data without agent reasoning.

    Query parameters:
        category:  Filter by category (work, interview_prep, learning, personal, hobby).
        status:    Filter by status. Omit to exclude done/archived.
        item_type: Filter by type (task, article, video, course, dsa_problem, note, idea).
        sort_by:   "priority" (desc, default), "due_date" (asc), "created_at" (desc).
        limit:     Max items to return (1–200, default 20).

    Returns:
        {"items": [...], "count": N}
    """
    try:
        db = get_supabase()
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

        items = result.data or []
        return {"items": items, "count": len(items)}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {e}")
