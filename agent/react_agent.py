from typing import Any, Dict

import rich

from agent.llminterface.client.llm_client import LLMClient
from agent.llminterface.client.llm_chat import LLMChat, LLMMessage
from agent.llminterface.agent_graph.agent_graph import AgentGraph, END
from agent.llminterface.agent_chain.execs import *
from agent.tools import tools_spec, run_tool_calls
import json

MAX_REVISIONS = 2


def build_agent(client: LLMClient) -> AgentGraph:




    chain_orchestrator = (
        ExecEffect({
            "model": lambda d: f"Оркестратор ({d["orchestrator_model"]})",
            "on_start_message": lambda d: d["on_start_message"]
            }
            | ExecLambda(lambda d: d["on_start_message"](d["model"]))
        )
        | ExecUpdate(
            chat=(
                ExecUpdate(
                    chat=(lambda d: LLMChat([{"role": "system", "content": d["orchestrator_prompt"]}]) + d["chat"])
                )
                | ExecSelect(
                    chat="chat",
                    model="orchestrator_model",
                    tools="tools",
                    on_chunk_think="on_think",
                    on_chunk_content="on_content",
                    num_ctx="num_ctx_orchestrator"
                )
                | ExecMultiargument(client)
            )
        )
        | ExecEffect({
                        "message": lambda d: d["chat"][-1],
                        "model": lambda d: f"Оркестратор ({d["orchestrator_model"]})",
                        "on_end_message": lambda d: d["on_end_message"]
                     }
                     | ExecEffect(lambda d: print(f"\n\n{d["model"]} --- ", end=""))
                     | ExecLambda(lambda d: d["on_end_message"](d["message"]))
        )
        | {"chat": lambda d: d["chat"], "answer_candidate": lambda d: d["chat"][-1].content}
    )


    def route_model(state) -> Any:
        return "toolNode" if state["chat"][-1].tool_calls else "reflection"


    def tool_node(state) -> Dict[str, Any]:
        calls = state["chat"][-1].tool_calls or []

        chat = state["chat"]

        if state.get("on_tool"):
            for call in calls:
                name = call["function"]["name"]
                result = state["on_tool"](json.dumps({
                    "type": "client",
                    "command": {
                        "name": name,
                        "arguments": call["function"]["arguments"]
                    }
                }))
                chat = chat + LLMMessage.tool_result(name, result, call.get("id"))

        return {"chat": chat}


    chain_reflector = (
        ExecEffect({
            "model": lambda d: f"Рефлектор ({d['reflector_model']})",
            "on_start_message": lambda d: d["on_start_message"]
            }
            | ExecLambda(lambda d: d["on_start_message"](d["model"]))
        )
        | ExecUpdate(
            chat=(
                ExecUpdate(
                    chat=(lambda d: (d["chat"]) + LLMChat([{"role": "system", "content": d["reflector_prompt"]}]))
                )
                | ExecSelect(
                    chat="chat",
                    model="reflector_model",
                    on_chunk_think="on_think",
                    on_chunk_content="on_content",
                    num_ctx="num_ctx_reflector"
                )
                | ExecMultiargument(client)
            )
        )
        | ExecEffect({
                        "message": lambda d: d["chat"][-1],
                        "model": lambda d: f"Рефлектор ({d['reflector_model']})",
                        "on_end_message": lambda d: d["on_end_message"]
                     }
                     | ExecEffect( lambda d: print(f"\n\n{d["model"]} --- ", end=""))
                     | ExecLambda(lambda d: d["on_end_message"](d["message"]))
        )
        | {
            "chat": lambda d: d["chat"],
            "revisions": lambda d: d["revisions"] + 1,
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
        ExecEffect({
            "model": lambda d: f"Именователь ({d['namer_model']})",
            "on_start_message": lambda d: d["on_start_message"]
            }
            | ExecLambda(lambda d: d["on_start_message"](d["model"]))
        )
        | ExecUpdate(
            chat=(
                ExecUpdate(
                    chat=(lambda d: LLMChat([{"role": "system", "content": d["namer_prompt"]}]) + d["chat"])
                )
                | ExecSelect(
                    chat="chat",
                    model="namer_model",
                    num_ctx="num_ctx_namer"
                )
                | ExecMultiargument(client)
            )
        )
        | ExecEffect({
                        "message": lambda d: d["chat"][-1],
                        "model": lambda d: f"Именователь ({d['namer_model']})",
                        "on_end_message": lambda d: d["on_end_message"]
                     }
                     | ExecEffect(lambda d: print(f"\n\n{d["model"]} --- ", end=""))
                     | ExecLambda(lambda d: d["on_end_message"](d["message"]))
        )
        | ExecEffect(lambda d: d["on_title"](d["chat"][-1].content))
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
