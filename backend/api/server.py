from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from pydantic import BaseModel, Field

from agent.graph import build_agent, run_with_memory
from db import local_store

load_dotenv()

_agent = None


class ChatRequest(BaseModel):
    message: str
    thread_id: str = "default"


class StepOut(BaseModel):
    type: str
    content: str | None = None
    tool_name: str | None = None
    tool_input: Any | None = None


class ChatResponse(BaseModel):
    answer: str
    steps: list[StepOut] = Field(default_factory=list)


class TagCreate(BaseModel):
    name: str


class TaskCreate(BaseModel):
    title: str
    parent_task_id: str | None = None
    description: str = ""
    due_at: str | None = None
    tag_ids: list[str] = Field(default_factory=list)
    tag_names: list[str] = Field(default_factory=list)


class SubtaskCreate(BaseModel):
    title: str


class TaskUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    status: str | None = None
    due_at: str | None = None
    completed_at: str | None = None
    archived_at: str | None = None
    tag_ids: list[str] | None = None
    tag_names: list[str] | None = None


class AiCommand(BaseModel):
    input_text: str
    context: dict[str, Any] | None = None


class AiConfirm(BaseModel):
    overrides: dict[str, Any] | None = None


class AiAskRequest(BaseModel):
    question: str


class AiAskResponse(BaseModel):
    answer: str
    type: str
    tasks: list[Any] = Field(default_factory=list)


@asynccontextmanager
async def lifespan(app: FastAPI):
    local_store.init_db()
    yield


app = FastAPI(
    title="Akash Planner API",
    description="Local-first personal planning API with optional LLM assistance.",
    version="3.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _get_agent():
    global _agent
    if _agent is None:
        _agent = build_agent()
    return _agent


def _content_to_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict):
                parts.append(str(block.get("text") or block.get("content") or ""))
            else:
                parts.append(str(block))
        return "\n".join(part for part in parts if part)
    return str(content)


def _steps_from_messages(messages: list[Any]) -> list[StepOut]:
    steps: list[StepOut] = []
    for message in messages:
        if isinstance(message, HumanMessage):
            steps.append(StepOut(type="thought", content=_content_to_text(message.content)))
        elif isinstance(message, AIMessage):
            tool_calls = getattr(message, "tool_calls", None) or []
            if tool_calls:
                for call in tool_calls:
                    steps.append(
                        StepOut(
                            type="action",
                            tool_name=call.get("name"),
                            tool_input=call.get("args"),
                            content=_content_to_text(message.content) or None,
                        )
                    )
            elif _content_to_text(message.content):
                steps.append(StepOut(type="answer", content=_content_to_text(message.content)))
        elif isinstance(message, ToolMessage):
            steps.append(
                StepOut(
                    type="observation",
                    tool_name=getattr(message, "name", None),
                    content=_content_to_text(message.content),
                )
            )
    return steps


@app.get("/health")
async def health() -> dict[str, str]:
    local_store.init_db()
    return {"status": "ok"}


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    try:
        result = run_with_memory(
            _get_agent(),
            request.thread_id,
            [HumanMessage(content=request.message)],
        )
        messages = result.get("messages", [])
        answer = ""
        if messages:
            answer = _content_to_text(messages[-1].content).strip()
        return ChatResponse(answer=answer, steps=_steps_from_messages(messages))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/dashboard")
async def api_dashboard() -> dict[str, Any]:
    local_store.init_db()
    return local_store.dashboard()


@app.post("/api/workspace/clear")
async def api_clear_workspace() -> dict[str, bool]:
    local_store.init_db()
    local_store.clear_workspace()
    return {"cleared": True}


@app.get("/api/tags")
async def api_list_tags() -> list[dict[str, Any]]:
    local_store.init_db()
    return local_store.list_tags()


@app.post("/api/tags")
async def api_create_tag(payload: TagCreate) -> dict[str, Any]:
    local_store.init_db()
    return local_store.get_or_create_tag(payload.name)


@app.get("/api/tasks")
async def api_list_tasks(
    tag_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    include_archived: bool = Query(default=False),
    with_subtasks: bool = Query(default=False),
) -> list[dict[str, Any]]:
    local_store.init_db()
    return local_store.list_tasks(
        tag_id=tag_id,
        status=status,
        include_archived=include_archived,
        with_subtasks=with_subtasks,
    )


@app.post("/api/tasks")
async def api_create_task(payload: TaskCreate) -> dict[str, Any]:
    local_store.init_db()
    return local_store.create_task(payload.model_dump())


@app.get("/api/tasks/{task_id}")
async def api_get_task(task_id: str) -> dict[str, Any]:
    local_store.init_db()
    task = local_store.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@app.patch("/api/tasks/{task_id}")
async def api_update_task(task_id: str, payload: TaskUpdate) -> dict[str, Any]:
    local_store.init_db()
    task = local_store.update_task(task_id, payload.model_dump(exclude_unset=True))
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@app.post("/api/tasks/{task_id}/subtasks")
async def api_create_subtask(task_id: str, payload: SubtaskCreate) -> dict[str, Any]:
    local_store.init_db()
    parent = local_store.get_task(task_id)
    if parent is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return local_store.create_task(
        {
            "title": payload.title,
            "parent_task_id": task_id,
        }
    )


@app.post("/api/tasks/{task_id}/complete")
async def api_complete_task(task_id: str) -> dict[str, Any]:
    local_store.init_db()
    task = local_store.complete_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@app.post("/api/tasks/{task_id}/archive")
async def api_archive_task(task_id: str) -> dict[str, Any]:
    local_store.init_db()
    task = local_store.archive_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@app.delete("/api/tasks/{task_id}")
async def api_delete_task(task_id: str) -> dict[str, bool]:
    local_store.init_db()
    deleted = local_store.delete_task(task_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"deleted": True}


@app.get("/api/suggestions/next")
async def api_suggest_next(limit: int = Query(default=3, ge=1, le=20)) -> list[dict[str, Any]]:
    local_store.init_db()
    return local_store.suggest_next_tasks(limit)


@app.post("/api/ai/command")
async def api_ai_command(payload: AiCommand) -> dict[str, Any]:
    local_store.init_db()
    return local_store.create_ai_draft(payload.input_text, payload.context)


@app.post("/api/ai/actions/{draft_id}/confirm")
async def api_ai_confirm(draft_id: str, payload: AiConfirm) -> dict[str, Any]:
    local_store.init_db()
    result = local_store.confirm_ai_draft(draft_id, payload.overrides)
    if result is None:
        raise HTTPException(status_code=404, detail="Draft not found")
    return result


@app.get("/api/summary")
async def api_summary() -> dict[str, str]:
    local_store.init_db()
    return {"summary": local_store.summarize_workspace()}


@app.post("/api/ai/ask")
async def api_ai_ask(payload: AiAskRequest) -> AiAskResponse:
    local_store.init_db()
    result = local_store.ai_ask(payload.question)
    return AiAskResponse(**result)


@app.get("/api/activity")
async def api_activity(days: int = Query(default=90, ge=1, le=400)) -> dict[str, Any]:
    local_store.init_db()
    return local_store.get_activity(days)
