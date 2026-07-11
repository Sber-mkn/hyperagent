"""Minimal ReAct graph with layered memory."""

from __future__ import annotations

from typing import Any, Callable

from agent.llminterface.agent_chain.execs import ExecEffect, ExecLambda, ExecUpdate
from agent.llminterface.agent_graph.agent_graph import END, AgentGraph
from agent.llminterface.client.llm_client import LLMClient
from agent.memory import Turn
from agent.tools import execute_tool, tool_target, truncate_middle


MAX_TOOL_RESULT_CHARS = 24_000
TOOL_PREVIEW_CHARS = 300


def build_agent(client: LLMClient) -> AgentGraph:
    """Build start -> model <-> tools -> finalize."""

    def prepare_context(state) -> dict[str, Any]:
        store = state["memory_store"]
        store.maybe_compress(state["memory_summarizer"].summarize)

        data = state.to_dict()
        data["chat"] = state["memory_context"].build_chat()
        data["iterations"] = state.get("iterations", 0) + 1
        return data

    def call_model(state):
        options = dict(state.get("model_options") or {})
        return client.stream(
            state["chat"],
            on_chunk_think=state.get("on_think"),
            on_chunk_content=state.get("on_content"),
            model=state["model"],
            tools=state["tools"],
            **options,
        )

    def record_assistant(state) -> None:
        message = state["chat"][-1]
        _emit(state.get("on_end_message"), message)
        state["memory_store"].append(
            Turn(
                role="assistant",
                content=message.content or "",
                tool_calls=message.tool_calls,
            )
        )

    model_node = (
        ExecLambda(prepare_context)
        | ExecEffect(
            lambda state: _emit(
                state.get("on_start_message"),
                f"Agent ({state['model']})",
            )
        )
        | ExecUpdate(chat=ExecLambda(call_model))
        | ExecEffect(record_assistant)
    )

    def start_node(state) -> dict[str, Any]:
        task = state["user_message"]
        state["memory_store"].set_task(task)
        _emit(state.get("on_title"), _title(task))
        return {"iterations": 0}

    def route_model(state):
        return "tools" if state["chat"][-1].tool_calls else "finalize"

    def tool_node(state) -> dict[str, Any]:
        for call in state["chat"][-1].tool_calls or []:
            _run_tool(state, call)
        return {}

    def route_tools(state):
        if state["iterations"] >= state["max_iterations"]:
            return "limit"
        return "model"

    def finalize_node(state) -> dict[str, str]:
        return {"answer": (state["chat"][-1].content or "").strip()}

    def limit_node(state):
        raise RuntimeError(
            f"Agent exceeded {state['max_iterations']} model iterations"
        )

    return (
        AgentGraph()
        .add_node("start", start_node)
        .add_node("model", model_node)
        .add_node("tools", tool_node)
        .add_node("finalize", finalize_node)
        .add_node("limit", limit_node)
        .set_entry("start")
        .add_edge("start", "model")
        .add_conditional_edge("model", route_model)
        .add_conditional_edge("tools", route_tools)
        .add_edge("finalize", END)
        .add_edge("limit", END)
    )


def _run_tool(state, call: dict[str, Any]) -> None:
    function = call.get("function") or {}
    name = function.get("name") or "unknown_tool"
    arguments = function.get("arguments") or "{}"
    target = tool_target(call)

    if target == "client":
        callback: Callable[[dict[str, Any]], Any] | None = state.get("on_tool")
        if callback is None:
            result = f"[client tool {name} unavailable]"
        else:
            response = callback(
                {
                    "type": "client_command",
                    "command": {"name": name, "arguments": arguments},
                }
            )
            result = response.get("result") if isinstance(response, dict) else response
    else:
        _, result = execute_tool(call)

    result_text = truncate_middle(str(result), MAX_TOOL_RESULT_CHARS)
    _emit(
        state.get("on_tool_call"),
        name,
        arguments,
        target,
        truncate_middle(result_text, TOOL_PREVIEW_CHARS),
    )
    state["memory_store"].append(
        Turn(
            role="tool",
            content=result_text,
            tool_name=name,
            tool_call_id=call.get("id"),
        )
    )


def _title(task: str) -> str:
    title = " ".join(task.split()) or "Agent task"
    return title if len(title) <= 60 else title[:57] + "..."


def _emit(callback: Callable[..., Any] | None, *args: Any) -> Any:
    return callback(*args) if callback else None
