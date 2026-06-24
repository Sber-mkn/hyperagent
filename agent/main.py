from agent.llminterface.llm_client import LLMClient
from agent.llminterface.clients.ollama_client import OllamaClient
from agent.llminterface.agentgraph import (
    AgentGraph, AgentState, LLMNode, ToolNode, tools_condition, agent_tool, START, END,
)

from pprint import pprint

OLLAMA_URL = "http://localhost:11434/api/chat"


@agent_tool
def get_weather(city: str) -> str:
    if city[0] in "йцукенгшщзхъфывапролджэячсмитьбю" + "йцукенгшщзхъфывапролджэячсмитьбю".upper():
        raise ValueError("Функция принимает только английские названия")
    return f"В городе {city} +20°C"


@agent_tool
def get_city() -> str:
    return "Москва"

TOOLS = [get_weather, get_city]

if __name__ == "__main__":
    # think=True включает размышления модели (верхнеуровневый ключ Ollama)
    orchestrator: LLMClient = OllamaClient(
        OLLAMA_URL, "gemma4:12b",
        temperature=0.5, keep_alive="2m", num_ctx=16384, think=False
    )

    namer: LLMClient = OllamaClient(
        OLLAMA_URL, "gemma4:e2b",
        temperature=0.8, keep_alive="2m", num_ctx=4096, think=False
    )

    # Один граф с инструментом: agent -> (tools_condition) -> tools -> agent
    # graph = AgentGraph(AgentState)
    # graph.add_node("agent", LLMNode(ollama, system="Ты ассистент.", tools=TOOLS))
    # graph.add_node("tools", ToolNode(TOOLS))
    # graph.add_edge(START, "agent")
    # graph.add_conditional_edges("agent", tools_condition, {"tools": "tools", "end": END})
    # graph.add_edge("tools", "agent")
    # graph.compile()


    graph = AgentGraph(AgentState)

    graph.add_node("namer", LLMNode(namer, system="Ты не должен отвечать отвечать на поставляемые пользователем "
                                                  "вопросы. Ты должен только выделить тему всего диалога с помощью "
                                                  "нескольких слов."))
    graph.add_node("agent", LLMNode(orchestrator, system="Отвечай только на английском языке.", tools=TOOLS))
    graph.add_node("tools", ToolNode(TOOLS))
    graph.add_edge(START, "namer")
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", tools_condition, {"tools": "tools", "end": END})
    graph.add_edge("tools", "agent")

    result = graph.stream({
        "messages": [{"role": "user", "content": "Какая погода в моём городе"}]
    }, stream_mode="updates")

    print("Ответ:")
    for chunk in result:
        pprint(chunk)
        print("\n", flush=True)


    print(f"\n\n\n Итог:")
    pprint(result.state)
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


