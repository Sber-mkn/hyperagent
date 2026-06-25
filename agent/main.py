from agent.llminterface.llm_client import LLMClient
from agent.llminterface.clients.ollama_client import OllamaClient
from agent.llminterface.agentgraph import (
    AgentGraph, AgentState, LLMNode, ToolNode, ToolEvent, tools_condition, reflector_condition, agent_tool, START, END,
)

from agent.tools.computer_tools import *

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


TOOLS = ALL_TOOLS + [get_city]

if __name__ == "__main__":
    orchestrator: LLMClient = OllamaClient(
        OLLAMA_URL, "gemma4:12b",
        temperature=0.5, keep_alive="2m", num_ctx=16384, think=False
    )

    reflector: LLMClient = OllamaClient(
        OLLAMA_URL, "gemma4:12b",
        temperature=0.5, keep_alive="2m", num_ctx=16384, think=False
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
    graph.add_node("agent", LLMNode(
        orchestrator,
        system="""
        Твоя задача любой ценой решать задачу поставленную пользователем.
        
        Для решения задачи ты можешь использовать любые инструменты, которые тебе доступны, перед решением задачи тебе необходимо ИЗУЧИТЬ ВСЕ ДОСТУПНЫЕ ИНСТРУМЕНТЫ.
        
        Ты можешь взаимодействовать с компьютером пользователя с помощью специальных инструментов, а также можешь генерировать код на любом языке с помощью инструмента generate_code.
        Если необходимо сгенерировать код, в котором будет использоваться API или библиотеки, тебе нужно будет проверить с помощью поиска в интернете как с ними работать, а также описать использование при вызове инструмента generate_code.
        
        Ты можешь запускать код, написанный на python с помощью инструмента run_python, однако учитывай, что библиотеки могут быть не установлены и тебе потребуется установить их.
        
        Ставь любые факты под сомнение и проверяй их с помощью инструментов для доступа в интернет, например какая сейчас дата, год и любые другие данные. 
        
        Выполняй задание с помощью мелких шагов которые возможно реализовать с помощью инстурментов.
        
        ВСЕГДА ПЫТАЙСЯ НАЙТИ ИНФОРМАЦИЮ В ИНТЕРНЕТЕ ВМЕСТО ТОГО, ЧТОБЫ ГЕНЕРИРОВАТЬ САМОМУ.
        """,
        tools=TOOLS)
                   )
    graph.add_node("reflector", LLMNode(
        reflector,
        system="Твоя задача объективно оценивать решение проблемы представленное в диалоге. Тебе доступны инструменты, "
               "но ты не должен из запускать, ты можешь их изучить, чтобы иметь полное представление о диалоге."
               "Ответь строго в формате JSON: approved=true если решение правильное, "
               "approved=false если нужно исправление, и comment с объяснением.",
        output_key=None,
        response_format=REFLECTOR_FORMAT,
        json_state_map={"approved": "approved", "comment": "reflection"},
        extra_state={"reflections": 1},
        tools=TOOLS
    ))

    def log_tool_event(event: ToolEvent) -> None:
        if event.is_call:
            print(f"\n[tool] {event.name}({event.args})", flush=True)
        elif event.error:
            print(f"[tool] {event.name} → ERROR: {event.error}", flush=True)
        else:
            print(f"[tool] {event.name} → {event.result!r}", flush=True)

    graph.add_node("tools", ToolNode(TOOLS, on_tool_event=log_tool_event))
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", tools_condition, {"tools": "tools", "end": "reflector"})
    graph.add_edge("tools", "agent")
    graph.add_conditional_edges("reflector", reflector_condition, {"agent": "agent", "end": END})

    result = graph.stream({
        "messages": [{"role": "user", "content": "Создай таблицу в excel с температурой за каждый день текущего года. "
                                                 "Над таблицей должен быть расположен график. Итоговый файл должен "
                                                 "располагаться в C://example"}]
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
