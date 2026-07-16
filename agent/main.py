"""Mutable agent entry point."""

from __future__ import annotations

from typing import Any, Callable

from agent.config import (
    AGENT_MODEL,
    AGENT_NUM_CTX,
    DATA_DIR,
    L2_TOKEN_BUDGET,
    LLM_PROVIDER,
    MAX_ITERATIONS,
    MAX_OUTPUT_TOKENS,
    OLLAMA_URL,
    OPENAI_API_KEY,
    OPENAI_BASE_URL,
    SUMMARIZER_MODEL,
)
from agent.completion import CompletionChecker
from agent.llminterface.agent_graph.agent_state import AgentState
from agent.llminterface.client.llm_client import LLMClient
from agent.llminterface.client.providers.ollama_client import OllamaClient
from agent.llminterface.client.providers.openai_client import OpenaiClient
from agent.memory import ContextManager, MemoryStore, Summarizer
from agent.react_agent import build_agent
from agent.skills import SkillManager
from agent.tools import tools_spec

AGENT_TYPE_TO_PROVIDER = {"local": "ollama", "api": "openai"}


def agent_logic(
    user_message: str,
    llm_chat: list[dict[str, Any]] | None = None,
    l3_memory: dict[str, Any] | None = None,
    agent_session: dict[str, Any] | None = None,
    error_text: str = "",
    on_think: Callable[[str], Any] | None = None,
    on_content: Callable[[str], Any] | None = None,
    on_title: Callable[[str], Any] | None = None,
    on_tool: Callable[[dict[str, Any]], Any] | None = None,
    on_tool_call: Callable[[str, Any, str, str], Any] | None = None,
    on_end_message: Callable[[Any], Any] | None = None,
    on_l3: Callable[[dict[str, Any]], Any] | None = None,
    on_start_message: Callable[[str], Any] | None = None,
) -> str:
    """Run one task and return the final assistant answer."""
    task = (user_message or "").strip()
    agent_session = agent_session or {}
    agent_config = agent_session.get("agent_config") or {}
    client, model_options = _build_client(agent_session.get("agent_type"), agent_config)
    requested_model = agent_config.get("AGENT_MODEL")
    model = requested_model if requested_model and requested_model != "auto" else AGENT_MODEL

    store = MemoryStore.from_llm_chat(
        llm_chat,
        L2_TOKEN_BUDGET,
        l3_memory=l3_memory,
    )
    skill_manager = SkillManager.open(client, SUMMARIZER_MODEL, DATA_DIR / "skills", model_options)
    agent = build_agent(client)
    final = agent.stream(
        AgentState(
            {
                "user_message": task,
                "model": model,
                "model_options": model_options,
                "tools": tools_spec(),
                "memory_store": store,
                "external_history": llm_chat is not None,
                "resume_task": bool(error_text),
                "agent_session": agent_session,
                "memory_context": ContextManager(
                    store,
                    recovery_notice=_rollback_notice(error_text),
                ),
                "memory_summarizer": Summarizer(client, SUMMARIZER_MODEL, model_options),
                "completion_checker": CompletionChecker(client, SUMMARIZER_MODEL, model_options),
                "skill_manager": skill_manager,
                "max_iterations": MAX_ITERATIONS,
                "on_think": on_think,
                "on_content": on_content,
                "on_title": on_title,
                "on_tool": on_tool,
                "on_tool_call": on_tool_call,
                "on_end_message": on_end_message,
                "on_l3": on_l3,
                "on_start_message": on_start_message,
            }
        )
    )
    return str(final.get("answer") or "").strip()


def _build_client(
    agent_type: str | None = None, agent_config: dict[str, Any] | None = None
) -> tuple[LLMClient, dict[str, Any]]:
    agent_config = agent_config or {}
    provider = AGENT_TYPE_TO_PROVIDER.get(agent_type, LLM_PROVIDER)

    if provider == "ollama":
        return OllamaClient(url=OLLAMA_URL), {
            "num_ctx": AGENT_NUM_CTX,
            "num_predict": MAX_OUTPUT_TOKENS,
        }
    if provider in {"openai", "openrouter", "api"}:
        return (
            OpenaiClient(
                base_url=OPENAI_BASE_URL,
                api_key=agent_config.get("OPENROUTER_API_KEY") or OPENAI_API_KEY,
            ),
            {"max_tokens": MAX_OUTPUT_TOKENS},
        )
    raise ValueError(f"Unsupported LLM_PROVIDER: {provider}")


def _rollback_notice(error_text: str) -> str:
    if not error_text:
        return ""
    return (
        "Recovery notice: the agent source code was rolled back after a failed "
        "modification. Conversation memory is stored separately and was preserved. "
        "Use all previous dialogue normally. The traceback below is diagnostic "
        "information, not a user message.\n\n"
        f"Rollback traceback:\n{error_text.strip()}"
    )


if __name__ == "__main__":
    from agent.ui import (
        on_end_message,
        on_start_message,
        on_think_and_content,
        on_title,
        on_tool,
        on_tool_call,
    )

    local_think, local_content = on_think_and_content()
    print(
        agent_logic(
            user_message=input("Request: "),
            on_think=local_think,
            on_content=local_content,
            on_title=on_title,
            on_tool=on_tool,
            on_tool_call=on_tool_call,
            on_end_message=on_end_message,
            on_start_message=on_start_message,
        )
    )
