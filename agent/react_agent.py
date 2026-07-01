from typing import Any, Dict

from agent.llminterface.client.llm_client import LLMClient
from agent.llminterface.client.llm_chat import LLMChat, LLMMessage
from agent.llminterface.agent_graph.agent_graph import AgentGraph, END
from agent.tools import tools_spec, run_tool_calls
from agent.ui import console, StreamPrinter, render_footer, render_tool_call

MAX_REVISIONS = 2


def build_agent(client: LLMClient, model: str, namer: str) -> AgentGraph:

    # model
    def model_node(state) -> Dict[str, Any]:
        console.rule("[bold cyan]модель[/bold cyan]")
        printer = StreamPrinter()
        chat = client.stream(
            state["chat"],
            on_chunk_think=printer.on_think,
            on_chunk_content=printer.on_content,
            model=model, tools=tools_spec(),
        )
        printer.done()
        render_footer(chat[-1])
        return {"chat": chat}

    def route_model(state) -> Any:
        return "toolNode" if state["chat"][-1].tool_calls else "reflection"

    # toolNode
    def tool_node(state) -> Dict[str, Any]:
        console.rule("[bold magenta]инструменты[/bold magenta]")
        calls = state["chat"][-1].tool_calls or []
        results = run_tool_calls(calls)
        chat = state["chat"]
        for call, (name, result) in zip(calls, results):
            args = call.get("function", call).get("arguments") or {}
            render_tool_call(name, args, result)
            chat = chat + LLMMessage.tool_result(name, result)
        return {"chat": chat}

    # reflection
    def reflection_node(state) -> Dict[str, Any]:
        console.rule("[bold yellow]рефлексия[/bold yellow]")
        critique_chat = LLMChat(state["chat"].to_payload() + [{
            "role": "user",
            "content": "Оцени свой последний ответ. Если он полный и верный — "
                       "начни ответ со слова OK. Иначе кратко скажи, что улучшить.",
        }])
        printer = StreamPrinter()
        result = client.stream(
            critique_chat,
            on_chunk_think=printer.on_think,
            on_chunk_content=printer.on_content,
            model=model,
        )
        printer.done()
        render_footer(result[-1])
        return {"reflection": result[-1].content, "revisions": state.get("revisions", 0) + 1}

    def route_reflection(state) -> Any:
        verdict = (state.get("reflection") or "").strip().lower()
        if verdict.startswith("ok") or state.get("revisions", 0) >= MAX_REVISIONS:
            return END
        return "model"

    def namer_node(state) -> Dict[str, Any]:
        first_user = next((m.content for m in state["chat"] if m.role == "user"), "")
        name_chat = LLMChat([
            {"role": "system", "content": "Придумай очень короткое название беседы "
                                          "(3-5 слов) по запросу пользователя. Ответь только названием."},
            {"role": "user", "content": first_user},
        ])
        title = client.send(name_chat, model=namer)[-1].content.strip()
        return {"title": title}

    return (AgentGraph()
            .add_node("start", lambda s: {})
            .add_node("model", model_node)
            .add_node("toolNode", tool_node)
            .add_node("reflection", reflection_node)
            .add_node("namer", namer_node)
            .set_entry("start")
            .add_edge("start", "model", "namer")
            .add_conditional_edge("model", route_model)
            .add_edge("toolNode", "model")
            .add_conditional_edge("reflection", route_reflection)
            .add_edge("namer", END))
