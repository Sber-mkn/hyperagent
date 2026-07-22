"""Mutable agent entry point."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from agent.completion import CompletionChecker
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
from agent.llminterface.agent_graph.agent_state import AgentState
from agent.llminterface.client.llm_client import LLMClient
from agent.llminterface.client.providers.ollama_client import OllamaClient
from agent.llminterface.client.providers.openai_client import OpenaiClient
from agent.memory import ContextManager, MemoryStore, Summarizer
from agent.react_agent import build_agent
from agent.skills import SkillManager
from agent.tools import tools_spec

AGENT_TYPE_TO_PROVIDER = {
    "local": "ollama",
    "api": "openai",
    "ollama": "ollama",
    "openai": "openai",
}
# The client's "api" session type is branded as OpenRouter (it collects an
# OPENROUTER_API_KEY, not an OpenAI one) — default its base_url to OpenRouter's
# real endpoint rather than falling through to OPENAI_BASE_URL's default of
# api.openai.com, which rejects OpenRouter keys outright. The distinct
# "openai" session type is real OpenAI and uses OPENAI_BASE_URL/OPENAI_API_KEY
# as-is (its default is already api.openai.com).
OPENROUTER_DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"


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
    on_error: Callable[[str], Any] | None = None,
) -> str:
    """Run one task and return the final assistant answer."""
    task = (user_message or "").strip()
    agent_session = agent_session or {}
    agent_config = agent_session.get("agent_config") or {}
    client, model_options = _build_client(agent_session.get("agent_type"), agent_config)
    model, auxiliary_model = _resolve_models(agent_config)

    store = MemoryStore.from_llm_chat(
        llm_chat,
        L2_TOKEN_BUDGET,
        l3_memory=l3_memory,
    )
    skill_manager = SkillManager.open(client, auxiliary_model, DATA_DIR / "skills", model_options)
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
                "memory_summarizer": Summarizer(client, auxiliary_model, model_options),
                "completion_checker": CompletionChecker(client, auxiliary_model, model_options),
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
        client_url = agent_config.get("OLLAMA_URL")
        url = _ollama_chat_url(client_url) if client_url else OLLAMA_URL
        return OllamaClient(url=url), {
            "num_ctx": AGENT_NUM_CTX,
            "num_predict": MAX_OUTPUT_TOKENS,
        }
    if provider in {"openai", "openrouter", "api"}:
        if agent_type == "api":
            base_url = OPENROUTER_DEFAULT_BASE_URL
            api_key = agent_config.get("OPENROUTER_API_KEY") or OPENAI_API_KEY
            key_name = "OPENROUTER_API_KEY"
        else:
            base_url = OPENAI_BASE_URL
            api_key = agent_config.get("OPENAI_API_KEY") or OPENAI_API_KEY
            key_name = "OPENROUTER_API_KEY" if provider == "openrouter" else "OPENAI_API_KEY"
        if not api_key:
            raise ValueError(f"{key_name} is required for provider '{provider}'")
        return (
            OpenaiClient(base_url=base_url, api_key=api_key),
            {"max_tokens": MAX_OUTPUT_TOKENS},
        )
    raise ValueError(f"Unsupported LLM_PROVIDER: {provider}")


def _resolve_models(agent_config: dict[str, Any]) -> tuple[str, str]:
    session_model = _model_name(agent_config.get("AGENT_MODEL"))
    model = session_model or _model_name(AGENT_MODEL)
    if not model:
        raise ValueError("AGENT_MODEL must be configured")

    auxiliary_model = _model_name(agent_config.get("SUMMARIZER_MODEL"))
    if not auxiliary_model:
        auxiliary_model = model if session_model else _model_name(SUMMARIZER_MODEL) or model
    return model, auxiliary_model


def _model_name(value: Any) -> str | None:
    model = str(value or "").strip()
    return model if model and model.lower() != "auto" else None


def _ollama_chat_url(base_url: str) -> str:
    """The client stores a bare Ollama base URL (it uses that directly to list
    /api/tags from the host). The agent runs inside Docker though, so a
    "localhost"/"127.0.0.1" address the user typed on their host machine has
    to be translated to the container-reachable host.docker.internal, and the
    /api/chat path (which OllamaClient posts to verbatim) has to be appended."""
    normalized = base_url.strip().rstrip("/")
    for loopback_host in ("localhost", "127.0.0.1"):
        normalized = normalized.replace(f"://{loopback_host}", "://host.docker.internal")
    return normalized + "/api/chat"


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
