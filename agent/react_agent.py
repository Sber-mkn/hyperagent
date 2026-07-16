"""Minimal ReAct graph with layered memory."""

from __future__ import annotations

from typing import Any, Callable

from agent.llminterface.agent_chain.execs import ExecEffect, ExecLambda, ExecUpdate
from agent.llminterface.agent_graph.agent_graph import END, AgentGraph
from agent.llminterface.client.llm_chat import LLMMessage
from agent.llminterface.client.llm_client import LLMClient
from agent.memory import Turn
from agent.tools import execute_tool, tool_target, tools_spec, truncate_middle


MAX_TOOL_RESULT_CHARS = 24_000
TOOL_PREVIEW_CHARS = 300
MAX_COMPLETION_RETRIES = 2
TOOL_FAILURE_NUDGE_THRESHOLD = 3


def build_agent(client: LLMClient) -> AgentGraph:
    """Build start -> model <-> tools -> finalize."""

    def prepare_context(state) -> dict[str, Any]:
        store = state["memory_store"]
        l3_update = store.maybe_compress(state["memory_summarizer"].summarize)
        if l3_update:
            _emit(state.get("on_l3"), l3_update)

        data = state.to_dict()
        chat = state["memory_context"].build_chat()
        feedback = state.get("completion_feedback")
        if feedback:
            chat += LLMMessage.from_message(
                {"role": "user", "content": feedback}
            )
        data["chat"] = chat
        data["completion_feedback"] = ""
        data["iterations"] = state.get("iterations", 0) + 1
        return data

    def call_model(state):
        options = dict(state.get("model_options") or {})
        content_chunks: list[str] = []
        chat = client.stream(
            state["chat"],
            on_chunk_think=state.get("on_think"),
            on_chunk_content=content_chunks.append,
            model=state["model"],
            tools=state["tools"],
            **options,
        )
        state["candidate_content_chunks"] = content_chunks
        return chat

    def record_assistant(state) -> None:
        message = state["chat"][-1]
        if message.tool_calls:
            _emit(state.get("on_end_message"), message)
            state["memory_store"].append(
                Turn(
                    role="assistant",
                    content=message.content or "",
                    thinking=message.thinking or "",
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
        appended = state["memory_store"].set_task(
            task,
            resume=state.get("resume_task", False),
        )
        if appended and state.get("external_history"):
            _emit(
                state.get("on_end_message"),
                LLMMessage.from_message({"role": "user", "content": task}),
            )
        _emit(state.get("on_title"), _title(task))
        return {
            "iterations": 0,
            "completion_retries": 0,
            "completion_feedback": "",
            "completion_verified": False,
            "review_available": True,
            "consecutive_tool_failures": 0,
            "last_tool_name": None,
        }

    def route_model(state):
        return "tools" if state["chat"][-1].tool_calls else "review"

    def tool_node(state) -> dict[str, Any]:
        refresh_tools = False
        consecutive_failures = state.get("consecutive_tool_failures", 0)
        last_tool_name = state.get("last_tool_name")
        for call in state["chat"][-1].tool_calls or []:
            refresh, name, failed = _run_tool(state, call)
            refresh_tools = refresh or refresh_tools
            if failed and name == last_tool_name:
                consecutive_failures += 1
            elif failed:
                consecutive_failures = 1
            else:
                consecutive_failures = 0
            last_tool_name = name

        updates: dict[str, Any] = {"tools": tools_spec()} if refresh_tools else {}
        updates["consecutive_tool_failures"] = consecutive_failures
        updates["last_tool_name"] = last_tool_name
        if consecutive_failures == TOOL_FAILURE_NUDGE_THRESHOLD:
            updates["completion_feedback"] = (
                f"The last {TOOL_FAILURE_NUDGE_THRESHOLD} attempts to use "
                f"'{last_tool_name}' failed. Before trying again, call "
                "skills_list to check for a relevant learned skill, or use web_search "
                "/ fetch_url to find documentation or a working example. Do not keep "
                "guessing blindly."
            )
        return updates

    def route_tools(state):
        if state["iterations"] >= state["max_iterations"]:
            return "limit"
        return "model"

    def review_node(state) -> dict[str, Any]:
        message = state["chat"][-1]
        store = state["memory_store"]
        review = state["completion_checker"].check(
            task=state["user_message"],
            turns=list(store.tail),
            candidate_answer=message.content or "",
            summaries=list(store.summaries),
        )
        if review.completed:
            return {
                "candidate_message": message,
                "completion_verified": True,
                "last_completion_reason": review.reason,
                "review_available": True,
            }

        retries = state.get("completion_retries", 0) + 1
        fix_instruction = (
            f"What to do: {review.fix} "
            if review.fix
            else "Continue the task with the required tools. "
        )
        return {
            "candidate_message": message,
            "completion_verified": False,
            "completion_retries": retries,
            "last_completion_reason": review.reason,
            "last_completion_fix": review.fix,
            "review_available": review.available,
            "completion_feedback": (
                "Your proposed final answer was not sent to the user because the "
                f"task is incomplete. Missing evidence: {review.reason} "
                f"{fix_instruction}"
                "Do not claim success until the result is verified."
            ),
        }

    def route_review(state):
        if state["completion_verified"]:
            return "finalize"
        if not state["review_available"]:
            return "verification_failed"
        if state["completion_retries"] >= MAX_COMPLETION_RETRIES:
            return "verification_failed"
        if state["iterations"] >= state["max_iterations"]:
            return "limit"
        return "model"

    def finalize_node(state) -> dict[str, str]:
        message = state["candidate_message"]
        answer = (message.content or "").strip()
        _emit(state.get("on_end_message"), message)
        state["memory_store"].append(
            Turn(role="assistant", content=answer, thinking=message.thinking or "")
        )
        chunks = state.get("candidate_content_chunks") or [answer]
        for chunk in chunks:
            _emit(state.get("on_content"), chunk)

        skill_manager = state["skill_manager"]
        learned_skills = skill_manager.consider(
            state["memory_store"].current_exchange(),
            completion_verified=True,
        )
        if learned_skills:
            details = "\n".join(
                f"Name: {skill.name}\nSaved to: {skill.path.as_posix()}"
                for skill in learned_skills
            )
            _emit(
                state.get("on_content"),
                f"\n\n[Skill{'s' if len(learned_skills) > 1 else ''} created]\n{details}",
            )
        else:
            _emit(
                state.get("on_content"),
                "\n\n[Skill not created]\n"
                f"Reason: {skill_manager.last_reason}",
            )
        return {"answer": answer}

    def verification_failed_node(state) -> dict[str, str]:
        reason = state.get("last_completion_reason") or "Unknown requirement"
        fix = state.get("last_completion_fix") or ""
        if state.get("review_available", True):
            answer = (
                "The task could not be verified after 2 correction attempts.\n\n"
                f"Missing requirement: {reason}\n\n"
                + (f"What was still needed: {fix}\n\n" if fix else "")
                + "The task remains incomplete. No skill was created."
            )
        else:
            answer = (
                "The task result could not be verified because the verification "
                f"step failed. Reason: {reason}\n\nNo skill was created."
            )
        _emit(state.get("on_content"), answer)
        return {"answer": answer}

    def limit_node(state):
        raise RuntimeError(
            f"Agent exceeded {state['max_iterations']} model iterations"
        )

    return (
        AgentGraph()
        .add_node("start", start_node)
        .add_node("model", model_node)
        .add_node("tools", tool_node)
        .add_node("review", review_node)
        .add_node("finalize", finalize_node)
        .add_node("verification_failed", verification_failed_node)
        .add_node("limit", limit_node)
        .set_entry("start")
        .add_edge("start", "model")
        .add_conditional_edge("model", route_model)
        .add_conditional_edge("tools", route_tools)
        .add_conditional_edge("review", route_review)
        .add_edge("finalize", END)
        .add_edge("verification_failed", END)
        .add_edge("limit", END)
    )


def _run_tool(state, call: dict[str, Any]) -> tuple[bool, str, bool]:
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
    failed = result_text.startswith("[ошибка инструмента") or result_text.startswith("[exit ")

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
    if state.get("external_history"):
        _emit(
            state.get("on_end_message"),
            LLMMessage.tool_result(name, result_text, call.get("id")),
        )
    return target == "server" and name == "create_tool", name, failed


def _title(task: str) -> str:
    title = " ".join(task.split()) or "Agent task"
    return title if len(title) <= 60 else title[:57] + "..."


def _emit(callback: Callable[..., Any] | None, *args: Any) -> Any:
    return callback(*args) if callback else None
