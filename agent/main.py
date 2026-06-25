from agent.llminterface.llm_client import LLMClient
from agent.llminterface.clients.ollama_client import OllamaClient
from agent.llminterface.agentgraph import (
    AgentGraph, AgentState, LLMNode, ToolNode, ToolEvent, tools_condition, reflector_condition, agent_tool, START, END,
)

from agent.tools.computer_tools import *

import os
import json
import textwrap

OLLAMA_URL = "http://localhost:11434/api/chat"


# ── Консольный вывод ─────────────────────────────────────────────────────────
class C:
    """ANSI-коды для оформления вывода"""
    RESET = "\033[0m"
    BOLD = "\033[1m"
    GRAY = "\033[90m"
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    CYAN = "\033[96m"
    MAGENTA = "\033[95m"


# цвет и подпись для каждого узла графа
NODE_STYLES = {
    "agent": (C.CYAN, "🧠 ОРКЕСТРАТОР"),
    "tools": (C.YELLOW, "🛠  ИНСТРУМЕНТЫ"),
    "reflector": (C.MAGENTA, "🔍 РЕФЛЕКТОР"),
}


def _enable_ansi() -> None:
    """Включает обработку ANSI-кодов в консоли Windows."""
    if os.name == "nt":
        try:
            import ctypes
            k = ctypes.windll.kernel32
            k.SetConsoleMode(k.GetStdHandle(-11), 7)
        except Exception:
            pass


def _banner(node: str) -> None:
    color, label = NODE_STYLES.get(node, (C.CYAN, node.upper()))
    print(f"\n\n{color}{C.BOLD}━━━ {label} {'━' * max(4, 50 - len(label))}{C.RESET}")


def render_stream(stream) -> None:
    """Красиво печатает поток графа: баннеры узлов, размышления (тускло) и ответы."""
    cur_node = None
    cur_type = None
    color = C.CYAN
    for node, chunk in stream:
        if node != cur_node:
            cur_node, cur_type = node, None
            color = NODE_STYLES.get(node, (C.CYAN, node))[0]
            _banner(node)
        if chunk.type != cur_type:
            cur_type = chunk.type
            tag = "💭 размышляет" if chunk.type == "thinking" else "💬 отвечает"
            sub = C.GRAY if chunk.type == "thinking" else color
            print(f"\n{sub}{C.BOLD}  {tag}:{C.RESET}")
        # цвет навешиваем на каждый токен — устойчиво к печати событий инструментов между ходами
        body = C.GRAY if chunk.type == "thinking" else C.RESET
        print(f"{body}{chunk.text}{C.RESET}", end="", flush=True)
    print()


def log_tool_event(event: "ToolEvent") -> None:
    """Печатает вызовы инструментов и их результаты."""
    if event.is_call:
        args = ", ".join(
            f"{k}={textwrap.shorten(str(v), 60, placeholder='…')}" for k, v in event.args.items()
        )
        print(f"\n{C.YELLOW}  ▶ {C.BOLD}{event.name}{C.RESET}{C.YELLOW}({args}){C.RESET}", flush=True)
    elif event.error:
        print(f"{C.RED}  ✖ {event.name}: {event.error}{C.RESET}", flush=True)
    else:
        preview = textwrap.shorten(str(event.result), 200, placeholder="…")
        print(f"{C.GREEN}  ✔ {preview}{C.RESET}", flush=True)


def final_answer(state: dict) -> str:
    """Возвращает последний содержательный ответ оркестратора.
    Пропускает пустые ходы и JSON-вердикт рефлектора (содержит ключ approved)."""
    for msg in reversed(state.get("messages", [])):
        if msg.get("role") != "assistant":
            continue
        content = (msg.get("content") or "").strip()
        if not content:
            continue
        try:
            parsed = json.loads(content)
            if isinstance(parsed, dict) and "approved" in parsed:
                continue
        except (json.JSONDecodeError, TypeError):
            pass
        return content
    return (state.get("output") or "").strip()


def render_result(state: dict) -> None:
    """Печатает итоговый ответ агента и вердикт рефлектора."""
    print(f"\n\n{C.GREEN}{C.BOLD}{'═' * 60}{C.RESET}")
    print(f"{C.GREEN}{C.BOLD}  ✅ ИТОГ{C.RESET}")
    print(f"{C.GREEN}{C.BOLD}{'═' * 60}{C.RESET}")
    print(final_answer(state) or f"{C.GRAY}(пустой ответ){C.RESET}")

    approved = state.get("approved")
    vcolor, verdict = (C.GREEN, "одобрено") if approved else (C.YELLOW, "требует доработки")
    print(f"\n{vcolor}{C.BOLD}Вердикт рефлектора: {verdict}{C.RESET}")
    if state.get("reflection"):
        print(f"{C.GRAY}{state['reflection']}{C.RESET}")


TOOLS = ALL_TOOLS


# ── Конфигурация графа ───────────────────────────────────────────────────────
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

ORCHESTRATOR_SYSTEM = """Ты — оркестратор автономного агента. Твоя цель — довести задачу пользователя до конца и убедиться в результате через инструменты, а не просто описать решение словами.

# Как ты работаешь
1. Разберись в задаче. Не выдумывай факты: текущую дату, год, версии, цены и любые внешние данные проверяй через web_search/fetch_url, а не по памяти.
2. Составь короткий план из маленьких шагов — каждый шаг выполним одним инструментом.
3. Выполняй план шаг за шагом, вызывая инструменты. После каждого вызова смотри на фактический результат и корректируй план.
4. Проверяй итог: прочитай созданный файл, запусти код, посмотри вывод. Объявляй задачу выполненной только после того, как убедился в результате через инструменты.

# Разделение труда: код пишешь не ты
Написание кода делегируй инструменту generate_code — за ним стоит специализированная модель-кодер. Твоя работа — поставить ей точное ТЗ, а затем запустить и проверить полученный код. Сам объёмный код вручную не пиши.
Цикл написания кода:
  а) Если используются внешние API или библиотеки — сначала через web_search уточни, как с ними работать, и передай это в requirements.
  б) Вызови generate_code с подробным description, при необходимости signature, requirements и examples.
  в) Запусти полученный код через run_python (Python) или сохрани файл и запусти через run_bash.
  г) Если код упал — прочитай ошибку, при необходимости установи зависимости (pip install через run_bash) и снова вызови generate_code, передав текст ошибки в requirements. Повторяй, пока не заработает.

# Выбор инструмента
- Свежие или внешние данные → web_search, затем fetch_url (fetch_url_render для страниц с JS).
- Написать код → generate_code (не пиши вручную).
- Выполнить код или команду → run_python, run_bash.
- Работа с файлами → list_files, read_file, write_file, change_file.

# Правила
- Действуй автономно: не спрашивай пользователя то, что можешь выяснить инструментами.
- Делай по одному маленькому проверяемому шагу за раз.
- Никогда не выдумывай вывод инструмента — дождись и используй фактический результат.
- Закончив, сообщи итог кратко и по делу, обязательно указав пути к созданным файлам."""

REFLECTOR_SYSTEM = (
    "Ты — строгий ревьюер. Тебе дан диалог, в котором агент решал задачу пользователя. "
    "Оцени объективно, действительно ли ИСХОДНАЯ задача решена полностью и корректно.\n\n"
    "Критерии:\n"
    "- Решены ли ВСЕ части задачи, а не только часть.\n"
    "- Подтверждён ли результат фактами из диалога (запущенный код, проверенный файл, реальный вывод "
    "инструментов), а не обещаниями агента.\n"
    "- Нет ли невыполненных шагов, ошибок инструментов без исправления или выдуманных данных.\n\n"
    "Инструменты тебе видны только для понимания контекста — ВЫЗЫВАТЬ их нельзя, анализируй уже произошедшее.\n\n"
    "Ответь строго в формате JSON: approved=true если задача полностью и корректно решена; "
    "approved=false если что-то не доделано или сделано неверно; "
    "comment — кратко, что подтверждает успех либо какие конкретные шаги агенту нужно выполнить для исправления."
)


def make_clients(url: str = OLLAMA_URL) -> tuple[LLMClient, LLMClient]:
    """Создаёт клиентов оркестратора (с рассуждением) и рефлектора (строгий JSON)."""
    orchestrator: LLMClient = OllamaClient(
        url, "qwen3.6:35b",
        temperature=0.4, keep_alive="10m", num_ctx=32768, think=True
    )
    reflector: LLMClient = OllamaClient(
        url, "qwen3.6:35b",
        temperature=0.3, keep_alive="10m", num_ctx=32768, think=False
    )
    return orchestrator, reflector


def build_graph(orchestrator: LLMClient, reflector: LLMClient,
                tools: list = None, on_tool_event=log_tool_event) -> AgentGraph:
    """Собирает граф agent → tools → reflector. Граф не хранит состояния прогона,
    поэтому одну сборку можно переиспользовать для разных задач."""
    tools = TOOLS if tools is None else tools

    graph = AgentGraph(AgentState)
    graph.add_node("agent", LLMNode(orchestrator, system=ORCHESTRATOR_SYSTEM, tools=tools))
    graph.add_node("reflector", LLMNode(
        reflector,
        system=REFLECTOR_SYSTEM,
        output_key=None,
        response_format=REFLECTOR_FORMAT,
        json_state_map={"approved": "approved", "comment": "reflection"},
        extra_state={"reflections": 1},
        tools=tools,
    ))
    graph.add_node("tools", ToolNode(tools, on_tool_event=on_tool_event))
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", tools_condition, {"tools": "tools", "end": "reflector"})
    graph.add_edge("tools", "agent")
    graph.add_conditional_edges("reflector", reflector_condition, {"agent": "agent", "end": END})
    return graph


if __name__ == "__main__":
    _enable_ansi()
    orchestrator, reflector = make_clients()
    graph = build_graph(orchestrator, reflector)

    task = ("Создай таблицу в excel с реальной температурой за каждый день текущего года. "
            "Над таблицей должен быть расположен график. Итоговый файл должен располагаться в C://example")

    print(f"{C.BOLD}ЗАДАЧА:{C.RESET} {task}")

    result = graph.stream({
        "messages": [{"role": "user", "content": task}]
    }, stream_mode="messages")

    render_stream(result)
    render_result(result.state)
