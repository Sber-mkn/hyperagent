from typing import Any, Dict

from agent.llminterface.client.llm_client import LLMClient
from agent.llminterface.client.llm_chat import LLMChat, LLMMessage
from agent.llminterface.agent_graph.agent_graph import AgentGraph, END
from agent.llminterface.agent_chain.execs import *
from agent.tools import tools_spec, run_tool_calls
from agent.ui import print_section, render_summary, render_tool_call

MAX_REVISIONS = 2


def build_agent(client: LLMClient) -> AgentGraph:

    def print_title(title: str):
        print_section(title)

    def print_details(chat: LLMChat, name):
        render_summary(chat[-1], name)

    def print_tool(name, args, result):
        render_tool_call(name, args, result)


    chain_orchestrator = (
        {
            "chat": lambda d: LLMChat([{"role": "system", "content": d["orchestrator_prompt"]}]) + d["chat"],
            "model": lambda d: d["orchestrator_model"],
            "tools": lambda d: d["tools"],
            "on_chunk_think": lambda d: d["on_think"],
            "on_chunk_content": lambda d: d["on_content"]
        }
        | ExecEffect(ExecLambda(lambda d: f"Оркестратор ({d['model']})") | print_title)
        | {"chat": ExecMultiargument(client)}
        | ExecEffect(ExecLambda(lambda d: d["chat"]) | ExecPartial(print_details, name="Оркестратор"))
        | {"chat": lambda d: d["chat"], "answer_candidate": lambda d: d["chat"][-1].content}
    )


    def route_model(state) -> Any:
        return "toolNode" if state["chat"][-1].tool_calls else "reflection"

    # toolNode
    def tool_node(state) -> Dict[str, Any]:
        print_title("Инструменты")
        calls = state["chat"][-1].tool_calls or []
        results = run_tool_calls(calls)
        chat = state["chat"]
        for call, (name, result) in zip(calls, results):
            args = call.get("function", call).get("arguments") or {}
            print_tool(name, args, result)
            chat = chat + LLMMessage.tool_result(name, result)
        return {"chat": chat}

    chain_reflector = (
            {
                "chat": lambda d: d["chat"] + LLMChat([{"role": "system", "content": d["reflector_prompt"]}]),
                "model": lambda d: d["reflector_model"],
                "on_chunk_think": lambda d: d["on_think"],
                "on_chunk_content": lambda d: d["on_content"],
                "revisions": lambda d: d.get("revisions", 0)
            }
            | ExecEffect(ExecLambda(lambda d: f"Рефлектор ({d['model']})") | print_title)
            | {"chat": ExecMultiargument(client), "revisions": lambda d: d["revisions"] + 1}
            | ExecEffect(ExecLambda(lambda d: d["chat"]) | ExecPartial(print_details, name="Рефлектор"))
            | {
                "chat": lambda d: d["chat"],
                "revisions": lambda d: d["revisions"],
                "reflection": lambda d: d["chat"][-1].content,
            }
    )

    def route_reflection(state) -> Any:
        verdict = (state.get("reflection") or "").strip().lower()
        if verdict.startswith("окей") or state.get("revisions", 0) >= MAX_REVISIONS:
            return "finalize"                             # рефлектор принял (или лимит) -> фиксируем ответ
        return "model"

    # финал: в answer попадает именно ответ оркестратора, а не рефлектора
    def finalize_node(state) -> Dict[str, Any]:
        accepted = (state.get("reflection") or "").strip().lower().startswith("окей")
        return {"answer": state.get("answer_candidate"), "accepted": accepted}


    chain_namer = (
            {
                "chat": lambda d: d["chat"] + LLMChat([{"role": "system", "content": d["namer_prompt"]}]),
                "model": lambda d: d["namer_model"]
            }
            | ExecEffect(ExecLambda(lambda d: f"Именователь ({d['model']})") | print_title)
            | {"chat": ExecMultiargument(client)}
            | ExecEffect(ExecLambda(lambda d: d["chat"]) | ExecPartial(print_details, name="Именователь"))
            | {"title": lambda d: d["chat"][-1].content}
    )

    return (AgentGraph()
            .add_node("start", lambda s: {})
            .add_node("model", chain_orchestrator)
            .add_node("toolNode", tool_node)
            .add_node("reflection", chain_reflector)
            .add_node("finalize", finalize_node)
            .add_node("namer", chain_namer)
            .set_entry("start")
            .add_edge("start", "model", "namer")
            .add_conditional_edge("model", route_model)
            .add_edge("toolNode", "model")
            .add_conditional_edge("reflection", route_reflection)
            .add_edge("finalize", END)
            .add_edge("namer", END))
