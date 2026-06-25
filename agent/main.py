from agent.llminterface.llm_client import LLMClient
from agent.llminterface.clients.ollama_client import OllamaClient
from agent.llminterface.agentgraph import (
    AgentGraph, AgentState, LLMNode, ToolNode, ToolEvent, tools_condition, reflector_condition, agent_tool, START, END,
)

from pprint import pprint

OLLAMA_URL = "http://100.93.59.55:11434/api/chat"


@agent_tool
def get_weather(city: str) -> str:
    if city[0] in "йцукенгшщзхъфывапролджэячсмитьбю" + "йцукенгшщзхъфывапролджэячсмитьбю".upper():
        raise ValueError("Функция принимает только английские названия")
    return f"В городе {city} +20°C"


@agent_tool
def get_city() -> str:
    """Функция для автоматического определения города пользователя"""
    return "Москва"


TOOLS = [get_weather, get_city]

if __name__ == "__main__":
    orchestrator: LLMClient = OllamaClient(
        OLLAMA_URL, "gemma4:12b",
        temperature=0.5, keep_alive="2m", num_ctx=16384, think=True
    )

    reflector: LLMClient = OllamaClient(
        OLLAMA_URL, "gemma4:12b",
        temperature=0.5, keep_alive="2m", num_ctx=16384, think=True
    )

    namer: LLMClient = OllamaClient(
        OLLAMA_URL, "gemma4:e2b",
        temperature=0.8, keep_alive="2m", num_ctx=4096, think=False
    )

    REFLECTOR_FORMAT = {
        "type": "object",
        "properties": {
            "approved": {
                "type": "boolean",
                "description": "true если ответ агента правильный и полный, false если нужно исправление"
            },
            "comment": {
                "type": "string",
                "description": "Краткое объяснение решения или что именно нужно исправить"
            }
        },
        "required": ["approved", "comment"]
    }

    graph = AgentGraph(AgentState)

    graph.add_node("namer", LLMNode(namer, system="Ты не должен отвечать отвечать на поставляемые пользователем "
                                                  "вопросы. Ты должен только выделить тему всего диалога с помощью "
                                                  "нескольких слов."))
    graph.add_node("agent", LLMNode(orchestrator, system="Отвечай только на английском языке.", tools=TOOLS))
    graph.add_node("reflector", LLMNode(
        reflector,
        system="Твоя задача объективно оценивать решение проблемы представленное в диалоге. "
               "Ответь строго в формате JSON: approved=true если решение правильное, "
               "approved=false если нужно исправление, и comment с объяснением.",
        output_key=None,
        response_format=REFLECTOR_FORMAT,
        json_state_map={"approved": "approved", "comment": "reflection"},
        extra_state={"reflections": 1},
    ))
    def log_tool_event(event: ToolEvent) -> None:
        if event.is_call:
            print(f"\n[tool] {event.name}({event.args})", flush=True)
        elif event.error:
            print(f"[tool] {event.name} → ERROR: {event.error}", flush=True)
        else:
            print(f"[tool] {event.name} → {event.result!r}", flush=True)

    graph.add_node("tools", ToolNode(TOOLS, on_tool_event=log_tool_event))
    graph.add_edge(START, "namer")
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", tools_condition, {"tools": "tools", "end": "reflector"})
    graph.add_edge("tools", "agent")
    graph.add_conditional_edges("reflector", reflector_condition, {"agent": "agent", "end": END})

    result = graph.stream({
        "messages": [{"role": "user", "content": "Какая погода в моём городе"}]
    }, stream_mode="messages")

    print("ОТВЕТ")
    current_node: str = ""
    current_type: str = ""
    for chunk in result:
        if chunk[0] != current_node:
            current_node = chunk[0]
            print(f"\n\n{'-' * 30}{current_node}{'-' * 30}", flush=True)
            current_type = ""
        if chunk[1].type != current_type:
            current_type = chunk[1].type
            print(end="\n\n")
            print(current_type, end=":\n", flush=True)
        print(chunk[1].text, end="", flush=True)

    print(f"\n\n\n Итоговый ответ:")
    pprint(result.state["output"])
    #
    # result = graph.stream({
    #     "messages": [{"role": "user", "content": "Какая погода в моём городе"}]
    # }, stream_mode="values")
    #
    # print("Ответ:")
    # for chunk in result:
    #     pprint(chunk)
    #     print("\n", flush=True)

    # result = graph.stream({
    #     "messages": [{"role": "user", "content": "Какая погода в моём городе"}]
    # }, stream_mode="messages")
    # print("Ответ:")
    # for chunk in result:
    #     print(chunk, end="", flush=True)


