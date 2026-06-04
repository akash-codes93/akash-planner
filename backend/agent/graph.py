"""
LangGraph ReAct agent graph for akash-planner.

Builds a two-node StateGraph:
    agent node  → calls the LLM (with system prompt + tools bound)
    tools node  → executes whichever tool the LLM requested

The loop: agent → tools → agent → … → END (when LLM returns plain text)

Phase 2 addition: run_with_memory() wraps the compiled graph to provide
cross-session persistence via Supabase. It loads prior conversation history
before each run and saves new messages after completion.

Usage:
    from agent.graph import build_agent, run_with_memory

    agent = build_agent()
    for event in run_with_memory(agent, "What's in my backlog?", thread_id="cli-1"):
        ...
"""
import os

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import MessagesState
from langgraph.prebuilt import ToolNode

from agent.prompts import SYSTEM_PROMPT
from agent.tools import ALL_TOOLS
from db.memory import load_conversation, save_messages

load_dotenv()


def _get_llm():
    """Return a configured LLM instance based on LLM_PROVIDER env var.

    "ollama"   → ChatOllama (local, requires `ollama serve` running)
    "groq"     → ChatGroq  (cloud, requires GROQ_API_KEY)
    "gemini"   → ChatGoogleGenerativeAI (cloud, requires GEMINI_API_KEY, 1M tokens/day free)
    "mistral"  → ChatMistralAI (cloud, requires MISTRAL_API_KEY, free tier at console.mistral.ai)

    Raises:
        ValueError: if LLM_PROVIDER is not one of the supported values.
    """
    provider = os.environ.get("LLM_PROVIDER", "ollama").lower()

    if provider == "ollama":
        from langchain_ollama import ChatOllama

        model = os.environ.get("OLLAMA_MODEL", "qwen2.5:7b")
        return ChatOllama(model=model, temperature=0)

    if provider == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI

        model = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")
        api_key = os.environ.get("GEMINI_API_KEY", "")
        if not api_key:
            raise ValueError(
                "GEMINI_API_KEY is not set. Get a free key at aistudio.google.com."
            )
        return ChatGoogleGenerativeAI(model=model, google_api_key=api_key, temperature=0)

    if provider == "groq":
        from langchain_groq import ChatGroq

        model = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
        api_key = os.environ.get("GROQ_API_KEY", "")
        if not api_key:
            raise ValueError(
                "GROQ_API_KEY is not set. Add it to backend/.env when using LLM_PROVIDER=groq."
            )
        return ChatGroq(model=model, api_key=api_key, temperature=0)

    if provider == "mistral":
        from langchain_mistralai import ChatMistralAI

        model = os.environ.get("MISTRAL_MODEL", "mistral-small-latest")
        api_key = os.environ.get("MISTRAL_API_KEY", "")
        if not api_key:
            raise ValueError("MISTRAL_API_KEY not set.")
        return ChatMistralAI(model=model, api_key=api_key, temperature=0)

    raise ValueError(
        f"Unsupported LLM_PROVIDER='{provider}'. Use 'ollama', 'groq', 'gemini', or 'mistral'."
    )


def build_agent(use_supabase_memory: bool = True):
    """Build and compile the LangGraph ReAct agent.

    Returns a compiled StateGraph that accepts MessagesState input and
    supports multi-turn memory via MemorySaver checkpointing (within-session)
    and optionally Supabase persistence (cross-session, via run_with_memory).

    The graph structure:
        START → agent → (tool_calls?) → tools → agent → … → END

    Each invocation requires a config dict with thread_id for memory:
        config = {"configurable": {"thread_id": "session-123"}}
        result = agent.invoke({"messages": [HumanMessage("hi")]}, config=config)

    For cross-session memory, use run_with_memory() instead of calling the
    compiled graph directly.

    Args:
        use_supabase_memory: Stored on the returned graph object as an attribute
                             so run_with_memory() can check whether to persist.
                             Default True.

    Returns:
        Compiled LangGraph CompiledGraph instance with .use_supabase_memory attribute.
    """
    llm = _get_llm()
    llm_with_tools = llm.bind_tools(ALL_TOOLS)

    def agent_node(state: MessagesState) -> dict:
        """Call the LLM with system prompt prepended to the message history."""
        messages = [SystemMessage(content=SYSTEM_PROMPT)] + state["messages"]
        response: AIMessage = llm_with_tools.invoke(messages)
        return {"messages": [response]}

    def should_continue(state: MessagesState) -> str:
        """Route to 'tools' if the LLM made tool calls, else END."""
        last = state["messages"][-1]
        if isinstance(last, AIMessage) and last.tool_calls:
            return "tools"
        return END

    tool_node = ToolNode(ALL_TOOLS)

    graph = StateGraph(MessagesState)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", tool_node)

    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", should_continue)
    graph.add_edge("tools", "agent")

    checkpointer = MemorySaver()
    compiled = graph.compile(checkpointer=checkpointer)
    compiled.use_supabase_memory = use_supabase_memory  # type: ignore[attr-defined]
    return compiled


def run_with_memory(agent, user_input: str, thread_id: str):
    """Run the agent with cross-session Supabase memory, yielding stream events.

    This is a wrapper around agent.stream() that adds persistence:
    1. Loads prior conversation history from Supabase for thread_id.
    2. Prepends that history to the user's new message.
    3. Streams agent events (yielding each one as received).
    4. After the stream ends, saves all new messages to Supabase.

    The MemorySaver inside the compiled graph handles within-session speed.
    Supabase handles cross-session durability so memory survives restarts.

    Args:
        agent:      Compiled LangGraph agent from build_agent().
        user_input: The user's current message text.
        thread_id:  Session identifier. Use the same ID across restarts to
                    maintain conversation context.

    Yields:
        Raw LangGraph stream events (same shape as agent.stream() values).
    """
    use_supabase = getattr(agent, "use_supabase_memory", True)

    # Load prior history from Supabase and prepend to current message
    prior_messages = load_conversation(thread_id) if use_supabase else []
    new_human_message = HumanMessage(content=user_input)
    all_input_messages = prior_messages + [new_human_message]

    config = {"configurable": {"thread_id": thread_id}}
    input_state = {"messages": all_input_messages}

    # Collect all messages seen in this run so we can persist them after
    all_events: list = []

    for event in agent.stream(input_state, config=config, stream_mode="values"):
        all_events.append(event)
        yield event

    # Save new messages (everything after prior_messages) to Supabase
    if use_supabase and all_events:
        final_state = all_events[-1]
        all_messages_in_run = final_state.get("messages", [])
        # all_messages_in_run contains both prior history AND new messages.
        # save_messages skips already-persisted rows using the count offset.
        save_messages(thread_id, all_messages_in_run)
