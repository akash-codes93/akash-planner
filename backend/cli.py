"""
Interactive CLI for testing the akash-planner ReAct agent.

Streams agent events and prints each step with ANSI colors so you can
watch the Thought → Action → Observation loop in real time.

Usage:
    cd backend
    python cli.py

Commands:
    <any text>   — send a message to the agent
    quit / exit  — end the session
"""

import sys

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from agent.graph import build_agent, run_with_memory

# ---------------------------------------------------------------------------
# ANSI colour helpers
# ---------------------------------------------------------------------------

RESET = "\033[0m"
BOLD = "\033[1m"
CYAN = "\033[96m"      # THOUGHT
YELLOW = "\033[93m"    # ACTION
GREEN = "\033[92m"     # OBSERVATION
MAGENTA = "\033[95m"   # FINAL ANSWER
DIM = "\033[2m"        # prompt / separators


def _colour(text: str, code: str) -> str:
    return f"{code}{text}{RESET}"


# ---------------------------------------------------------------------------
# Event streaming
# ---------------------------------------------------------------------------

def stream_agent(agent, user_input: str, thread_id: str) -> None:
    """Stream agent events and print each step with colour-coded labels.

    Uses run_with_memory() so conversation history persists to Supabase across
    CLI restarts. Pass the same thread_id between sessions to resume memory.

    Steps printed:
        THOUGHT      — text content in an AIMessage that precedes tool calls
        ACTION       — tool name + JSON-formatted arguments
        OBSERVATION  — tool result from ToolMessage
        FINAL ANSWER — AIMessage with no tool_calls (the agent is done)

    Args:
        agent:      Compiled LangGraph agent from build_agent().
        user_input: The user's message text.
        thread_id:  Session identifier — reuse across restarts for memory.
    """
    for event in run_with_memory(agent, user_input, thread_id):
        messages = event.get("messages", [])
        if not messages:
            continue

        last = messages[-1]

        # ── Agent node: AIMessage ──────────────────────────────────────────
        if isinstance(last, AIMessage):
            # Text content (reasoning / thought)
            text = ""
            if isinstance(last.content, str):
                text = last.content.strip()
            elif isinstance(last.content, list):
                # Some models return content as a list of blocks
                text = " ".join(
                    block.get("text", "") if isinstance(block, dict) else str(block)
                    for block in last.content
                ).strip()

            if last.tool_calls:
                # THOUGHT + ACTION(s)
                if text:
                    print(_colour("THOUGHT", CYAN + BOLD) + f"  {text}")
                for tc in last.tool_calls:
                    import json as _json
                    args_str = _json.dumps(tc.get("args", {}), indent=2)
                    print(
                        _colour("ACTION", YELLOW + BOLD)
                        + f"  {tc['name']}\n"
                        + _colour(args_str, DIM)
                    )
            else:
                # FINAL ANSWER
                if text:
                    print()
                    print(_colour("FINAL ANSWER", MAGENTA + BOLD))
                    print(text)

        # ── Tools node: ToolMessage ────────────────────────────────────────
        elif isinstance(last, ToolMessage):
            content = last.content or ""
            name = getattr(last, "name", "") or ""
            label = f"OBSERVATION ({name})" if name else "OBSERVATION"
            print(_colour(label, GREEN + BOLD))
            print(content)
            print()


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def main() -> None:
    """Run the interactive CLI session."""
    print(_colour("Akash Planner — ReAct Agent", BOLD))
    print(_colour("Type 'quit' or 'exit' to end the session.", DIM))
    print(_colour("─" * 50, DIM))
    print()

    try:
        agent = build_agent()
    except Exception as e:
        print(f"Failed to build agent: {e}")
        print("Check that backend/.env exists with SUPABASE_URL, SUPABASE_KEY, and LLM_PROVIDER.")
        sys.exit(1)

    thread_id = "cli-session-1"

    while True:
        try:
            user_input = input(_colour("You: ", BOLD)).strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye.")
            break

        if not user_input:
            continue

        if user_input.lower() in ("quit", "exit"):
            print("Goodbye.")
            break

        print()
        try:
            stream_agent(agent, user_input, thread_id)
        except Exception as e:
            print(f"Agent error: {e}")
        print()
        print(_colour("─" * 50, DIM))
        print()


if __name__ == "__main__":
    main()
