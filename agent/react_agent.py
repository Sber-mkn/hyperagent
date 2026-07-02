from typing import Any, Dict

from math import floor, ceil
from unittest import result

from agent.llminterface.client.llm_client import LLMClient
from agent.llminterface.client.llm_chat import LLMChat, LLMMessage
from agent.llminterface.agent_graph.agent_graph import AgentGraph, END
from agent.llminterface.agent_chain.execs import *
from agent.tools import tools_spec, run_tool_calls

MAX_REVISIONS = 2
LINE_LEN = 60



def build_agent(client: LLMClient) -> AgentGraph:

    def print_title(title: str):
        n = (LINE_LEN - len(title) - 2) / 2
        print(f"{'=' * floor(n)} {title} {'=' * ceil(n)}")

    def print_details(chat: LLMChat, name):
        message = chat[-1]
        print(end="\n\n")
        print_title(f"Сводка ({name})")
        print(f"""Токены:
    prompt: {message.tokens.prompt}
    response: {message.tokens.response}
    total: {message.tokens.total}
    
Длительность:
    load: {message.duration.load / 1e9} секунд
    prompt: {message.duration.prompt / 1e9} секунд
    response: {message.duration.response / 1e9} секунд
    total: {message.duration.total / 1e9} секунд

Инструменты:
    {message.tool_calls}


""")

    def print_tool(name, args, result):
        print(f"""Вызван инструмент {name}
    Параметры:
        """, end="")
        s = "\n\t\t".join([f"{key}: {value}" for key, value in args.items()])
        print(s)
        print(f"\n\tРезультат: \n\t\t{result}")


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
            return END
        return "model"


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
            .add_node("namer", chain_namer)
            .set_entry("start")
            .add_edge("start", "model", "namer")
            .add_conditional_edge("model", route_model)
            .add_edge("toolNode", "model")
            .add_conditional_edge("reflection", route_reflection)
            .add_edge("namer", END))
