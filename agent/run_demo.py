"""Run the framework (LangGraph) agent on the SAME task as the no-framework version.

Local only — no cloud API, no tracing. Models are served by your local Ollama.

Usage:
    python run_demo.py
"""

import json
import os
import sys

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage

load_dotenv()
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# Local-only run: force Ollama and disable any cloud tracing BEFORE importing the graph.
os.environ["LLM_PROVIDER"] = "ollama"
os.environ.setdefault("ORCHESTRATOR_MODEL", "qwen2.5-coder:3b")
os.environ.setdefault("CODER_MODEL", "qwen2.5-coder:3b")
os.environ.setdefault("NAMER_MODEL", "qwen2.5-coder:3b")
os.environ.setdefault("REFLECTOR_MODEL", "qwen2.5-coder:3b")
os.environ["LANGCHAIN_TRACING_V2"] = "false"
os.environ["LANGSMITH_TRACING"] = "false"
os.environ.pop("LANGCHAIN_API_KEY", None)
os.environ.pop("LANGSMITH_API_KEY", None)

from graph import graph

# Orchestrator system prompt kept close to the no-framework version.
# (His version is just the first line; the short procedure is added so the small
#  local model actually calls get_city and stops instead of looping.)
SYSTEM_PROMPT = (
    "Отвечай только на английском языке.\n"
    "To answer the weather question:\n"
    "1. Call get_city to determine the user's city.\n"
    "2. Call get_weather with that city.\n"
    "3. Then reply with the weather as one short plain-text sentence (no JSON, no tool call)."
)

# Same task the no-framework agent runs (so both versions are comparable).
TASK = "Какая погода в моём городе"


def _is_empty_answer(content: str) -> bool:
    """True for blank text or any tool-call-shaped JSON stub (e.g. {"name": ...}).
    Small local models emit JSON for everything, so those are not real answers."""
    s = (content or "").strip()
    if not s:
        return True
    if s.startswith("```"):
        lines = s.splitlines()
        if len(lines) >= 3:
            s = "\n".join(lines[1:-1]).strip()
    try:
        obj = json.loads(s)
        if isinstance(obj, dict) and "name" in obj:
            return True
    except json.JSONDecodeError:
        pass
    return False


def main():
    inputs = {
        "messages": [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=TASK)],
        "iteration": 0,
    }

    print("ОТВЕТ")
    current_node = ""
    current_type = ""
    final_state = None

    try:
        # Single run: stream tokens for the trace AND collect the final state.
        for mode, data in graph.stream(
            inputs, {"recursion_limit": 50}, stream_mode=["messages", "values"]
        ):
            if mode == "values":
                final_state = data
                continue

            msg, meta = data
            node = str(meta.get("langgraph_node", ""))
            if node != current_node:
                current_node = node
                print(f"\n\n{'-' * 30}{current_node}{'-' * 30}", flush=True)
                current_type = ""

            m_type = getattr(msg, "type", "")
            if m_type != current_type:
                current_type = m_type
                print(end="\n\n")
                print(f"{current_type}:", flush=True)

            text = getattr(msg, "text", None)
            if text is None:
                content = getattr(msg, "content", "")
                text = content if isinstance(content, str) else str(content)
            print(text, end="", flush=True)
    except Exception as e:
        print("\n\nAgent failed to run on local Ollama.")
        print(f"Error: {e}\n")
        print("Make sure the local server is up:")
        print("  ollama serve")
        print("  ollama list   # should show qwen2.5-coder:3b")
        return

    print("\n\n\n Итоговый ответ:")
    final_answer = ""
    if final_state:
        messages = final_state.get("messages", [])
        # Prefer a real plain-text answer from the orchestrator.
        for m in reversed(messages):
            if getattr(m, "type", "") == "ai":
                content = getattr(m, "content", "")
                content = content if isinstance(content, str) else str(content)
                if not _is_empty_answer(content):
                    final_answer = content
                    break
        # Small models only emit JSON, so fall back to the last tool result.
        if not final_answer:
            for m in reversed(messages):
                if getattr(m, "type", "") == "tool":
                    content = getattr(m, "content", "")
                    final_answer = content if isinstance(content, str) else str(content)
                    break
    print(final_answer or "(no answer produced)")

    if final_state and final_state.get("conversation_title"):
        print("\nТема диалога:")
        print(final_state["conversation_title"])
    if final_state and final_state.get("reflection"):
        print("\nРефлексия:")
        print(final_state["reflection"])


if __name__ == "__main__":
    main()
