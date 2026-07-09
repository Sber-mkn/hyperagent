from typing import Optional, Callable, Any, Dict, List, Literal, Iterable

import json
import threading
import time

from agent.llminterface.client.llm_chat import LLMChat, LLMMessage
from agent.llminterface.client.llm_client import LLMClient
from agent.llminterface.client.providers.ollama_client import OllamaClient

from agent.llminterface.agent_chain.execs import *
from agent.llminterface.agent_graph.agent_graph import AgentGraph, END
from agent.llminterface.agent_graph.agent_state import AgentState

from agent.tools import tools_spec, truncate_middle


OLLAMA_URL = "http://localhost:11434/api/chat"

PLANNER_MODEL = "ornith:9b"
NAMER_MODEL = "gemma4:e2b"
SUMMARIZER_MODEL = "ornith:9b"
FINALIZER_MODEL = "ornith:9b"

DEFAULT_GROUP = "thought"

NUM_CTX_PLANNER = 110000
NUM_CTX_NAMER = 24000
NUM_CTX_EXECUTOR = 110000
NUM_CTX_SUMMARIZER = 110000
NUM_CTX_FINALIZER = 110000

MAX_SUBTASK_STEPS = 10
MAX_SUBTASK_REVISIONS = 2
MAX_TOOL_RESULT_CHARS = 24000

SUBTASK_KEEP_ROUNDS = 3    # сколько последних раундов "вызов инструмента -> результат" хранить внутри подзадачи целиком
SUBTASK_COMPACT_CHARS = 300  # до скольки символов сжимать содержимое/аргументы более старых раундов

CONTROL_TOOL_NAMES = {"finish_subtask", "submit_plan"}


class ModelSpec:
    """Реестр моделей по группам (специализация) и уровням (сложность)."""

    groups: Dict[str, Dict[str, str]] = {}

    @classmethod
    def add(cls, model: str, group: str | Iterable[str], tier: str | Iterable[str] = ("low", "high")):
        groups = [group] if isinstance(group, str) else list(group)
        tiers = [tier] if isinstance(tier, str) else list(tier)
        for g in groups:
            bucket = cls.groups.setdefault(g, {})
            for t in tiers:
                bucket[t] = model

    @classmethod
    def get(cls, group: str, tier: str) -> Optional[str]:
        bucket = cls.groups.get(group)
        if not bucket:
            return None
        model = bucket.get(tier)
        if model is None and tier == "low":
            return bucket.get("high")
        return model

    @classmethod
    def get_groups(cls) -> List[str]:
        return list(cls.groups.keys())


def add_models():
    ModelSpec.add("ornith:9b", "thought", "low")
    ModelSpec.add("ornith:35b", "thought", "high")
    ModelSpec.add("ornith:9b", "coding", "low")
    ModelSpec.add("ornith:35b", "coding", "high")
    ModelSpec.add("gemma4:12b", "translating", "high")


add_models()

GROUP_DESCRIPTIONS: Dict[str, str] = {
    "thought": "рассуждения, ответы на вопросы, поиск информации, общие задачи без узкой специализации",
    "coding": "написание, чтение, отладка и выполнение кода",
    "translating": "перевод текста"
}


def _resolve_model(group: str, tier: str) -> str:
    model = ModelSpec.get(group, tier)
    if model is None:
        print(f"[предупреждение] группа моделей '{group}' не найдена, использую запасную группу '{DEFAULT_GROUP}'")
        model = ModelSpec.get(DEFAULT_GROUP, tier) or ModelSpec.get(DEFAULT_GROUP, "high")
    return model


def _tool_args(call: Dict[str, Any]) -> Dict[str, Any]:
    fn = call.get("function", call)
    args = fn.get("arguments")
    if isinstance(args, str):
        try:
            return json.loads(args or "{}")
        except json.JSONDecodeError:
            return {}
    return dict(args or {})


SUBMIT_PLAN_TOOL = {
    "type": "function",
    "function": {
        "name": "submit_plan",
        "description": "Отправить план решения задачи пользователя в виде списка подзадач.",
        "parameters": {
            "type": "object",
            "properties": {
                "subtasks": {
                    "type": "array",
                    "description": "Список подзадач в порядке выполнения",
                    "items": {
                        "type": "object",
                        "properties": {
                            "description": {"type": "string", "description": "Самодостаточное описание подзадачи"},
                            "group": {"type": "string", "description": "Группа моделей, лучше всего подходящая для подзадачи"},
                            "tier": {"type": "string", "enum": ["low", "high"], "description": "Уровень сложности подзадачи"},
                        },
                        "required": ["description", "group", "tier"],
                    },
                }
            },
            "required": ["subtasks"],
        },
    },
}

FINISH_SUBTASK_TOOL = {
    "type": "function",
    "function": {
        "name": "finish_subtask",
        "description": "Завершить работу над текущей подзадачей. Обязательно вызови этот инструмент, когда "
                        "подзадача решена, либо когда дальнейшие попытки её решить бессмысленны.",
        "parameters": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["success", "failed"], "description": "Итог решения подзадачи"},
                "result": {"type": "string", "description": "Итоговый результат/ответ по подзадаче"},
                "reason": {"type": "string", "description": "Если status=failed — что помешало решить подзадачу"},
            },
            "required": ["status", "result"],
        },
    },
}


def _format_plan(plan: List[Dict[str, Any]]) -> str:
    return "\n".join(f"{i + 1}. [{st['group']}/{st['tier']}] {st['description']}" for i, st in enumerate(plan))


def _format_summaries(summaries: List[Dict[str, Any]]) -> str:
    if not summaries:
        return "(пока нет выполненных подзадач)"
    lines = []
    for s in summaries:
        status_text = "успешно" if s["status"] == "success" else "с проблемой"
        lines.append(f"- Подзадача {s['index'] + 1} ({status_text}): {s['description']}\n  Итог: {s['summary']}")
    return "\n".join(lines)


def _compact_subtask_chat(chat: LLMChat) -> LLMChat:
    """Сжимает старые раунды 'вызов инструмента -> результат' внутри подзадачи.

    Без этого каждый шаг исполнителя пересылает модели ВСЮ накопленную историю
    подзадачи заново (см. tool_node — результаты только дописываются в chat), и
    промпт-токены растут почти квадратично с числом шагов вплоть до MAX_SUBTASK_STEPS.
    Системный промпт (0) и постановка подзадачи (1) не трогаем; последние
    SUBTASK_KEEP_ROUNDS раундов оставляем как есть, более старые — сжимаем:
    длинные аргументы вызовов и содержимое результатов инструментов урезаем
    truncate_middle'ом. Раунд начинается с сообщения ассистента, вызывающего
    инструмент(ы)."""
    messages = list(chat.data)
    round_starts = [i for i, m in enumerate(messages) if m.role == "assistant" and m.tool_calls]
    if len(round_starts) <= SUBTASK_KEEP_ROUNDS:
        return chat

    keep_from = round_starts[-SUBTASK_KEEP_ROUNDS]
    compacted: List[LLMMessage] = []
    for i, m in enumerate(messages):
        if i < 2 or i >= keep_from:
            compacted.append(m)
            continue
        if m.role == "tool":
            m = m.model_copy(update={"content": truncate_middle(m.content, SUBTASK_COMPACT_CHARS)})
        elif m.role == "assistant" and m.tool_calls:
            shrunk_calls = []
            for c in m.tool_calls:
                fn = dict(c.get("function", {}))
                args = fn.get("arguments")
                if isinstance(args, str) and len(args) > SUBTASK_COMPACT_CHARS:
                    fn["arguments"] = truncate_middle(args, SUBTASK_COMPACT_CHARS)
                elif isinstance(args, dict):
                    fn["arguments"] = {
                        k: (truncate_middle(v, SUBTASK_COMPACT_CHARS) if isinstance(v, str) else v)
                        for k, v in args.items()
                    }
                shrunk = dict(c)
                shrunk["function"] = fn
                shrunk_calls.append(shrunk)
            m = m.model_copy(update={"tool_calls": shrunk_calls})
        compacted.append(m)
    return LLMChat(compacted)


def _subtask_system_prompt(d: Dict[str, Any]) -> str:
    plan = d["plan"]
    index = d["subtask_index"]
    current = plan[index]
    return (
        f"{d['executor_prompt']}\n\n"
        f"Общий план решения задачи пользователя:\n{_format_plan(plan)}\n\n"
        f"Сводки уже выполненных подзадач:\n{_format_summaries(d['summaries'])}\n\n"
        f"Твоя текущая подзадача ({index + 1}/{len(plan)}): {current['description']}\n\n"
        "Когда полностью решишь свою подзадачу — обязательно вызови инструмент finish_subtask с status='success' "
        "и result — итоговым результатом. Если понимаешь, что не можешь решить подзадачу — вызови finish_subtask "
        "с status='failed' и reason — причиной."
    )


def create_agent(client: LLMClient) -> AgentGraph:

    chain_planner = (
        ExecEffect({
            "model": lambda d: f"Планировщик ({d['planner_model']})",
            "on_start_message": lambda d: d["on_start_message"]
            }
            | ExecLambda(lambda d: d["on_start_message"](d["model"]))
        )
        | ExecUpdate(
            plan_chat=(
                ExecUpdate(
                    plan_chat=(lambda d: LLMChat([{"role": "system", "content": d["planner_prompt"]}]) + d["chat"])
                )
                | ExecSelect(
                    chat="plan_chat",
                    model="planner_model",
                    tools="planner_tools",
                    on_chunk_think="on_think",
                    on_chunk_content="on_content",
                    num_ctx="num_ctx_planner"
                )
                | ExecMultiargument(client)
            )
        )
        | ExecEffect({
                        "message": lambda d: d["plan_chat"][-1],
                        "model": lambda d: f"Планировщик ({d['planner_model']})",
                        "on_end_message": lambda d: d["on_end_message"]
                     }
                     | ExecEffect(lambda d: print(f"\n\n{d['model']} --- ", end=""))
                     | ExecLambda(lambda d: d["on_end_message"](d["message"]))
        )
        | ExecLambda(lambda d: _build_plan(d))
    )

    def route_executor(state) -> Any:
        last = state["chat"][-1]
        calls = last.tool_calls or []
        has_finish = any(c["function"]["name"] == "finish_subtask" for c in calls)
        if has_finish:
            return "handle_finish"
        if state["subtask_steps"] >= MAX_SUBTASK_STEPS:
            return "handle_finish"
        if calls:
            return "toolNode"
        return "remind"

    def dispatch_node(state) -> Dict[str, Any]:
        current = state["plan"][state["subtask_index"]]
        model = _resolve_model(current["group"], current["tier"])
        system_prompt = _subtask_system_prompt(state.to_dict() if hasattr(state, "to_dict") else dict(state))
        chat = LLMChat([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Реши подзадачу: {current['description']}"},
        ])
        return {"chat": chat, "subtask_steps": 0, "subtask_revisions": 0, "executor_model": model}

    chain_executor = (
        ExecEffect({
            "model": lambda d: f"Исполнитель ({d['executor_model']})",
            "on_start_message": lambda d: d["on_start_message"]
            }
            | ExecLambda(lambda d: d["on_start_message"](d["model"]))
        )
        | ExecUpdate(
            chat=(
                ExecUpdate(chat=(lambda d: _compact_subtask_chat(d["chat"])))
                | ExecSelect(
                    chat="chat",
                    model="executor_model",
                    tools="executor_tools",
                    on_chunk_think="on_think",
                    on_chunk_content="on_content",
                    num_ctx="num_ctx_executor"
                )
                | ExecMultiargument(client)
            )
        )
        | ExecEffect({
                        "message": lambda d: d["chat"][-1],
                        "model": lambda d: f"Исполнитель ({d['executor_model']})",
                        "on_end_message": lambda d: d["on_end_message"]
                     }
                     | ExecEffect(lambda d: print(f"\n\n{d['model']} --- ", end=""))
                     | ExecLambda(lambda d: d["on_end_message"](d["message"]))
        )
        | {"chat": lambda d: d["chat"], "subtask_steps": lambda d: d["subtask_steps"] + 1}
    )

    def tool_node(state) -> Dict[str, Any]:
        calls = state["chat"][-1].tool_calls or []
        chat = state["chat"]

        if state.get("on_tool"):
            for call in calls:
                name = call["function"]["name"]
                if name in CONTROL_TOOL_NAMES:
                    continue
                result = state["on_tool"](json.dumps({
                    "type": "client",
                    "command": {
                        "name": name,
                        "arguments": call["function"]["arguments"]
                    }
                }))
                result = truncate_middle(str(result), MAX_TOOL_RESULT_CHARS)
                chat = chat + LLMMessage.tool_result(name, result, call.get("id"))

        return {"chat": chat}

    def remind_node(state) -> Dict[str, Any]:
        nudge = LLMMessage.from_message({
            "role": "user",
            "content": "Ты не вызвал ни один инструмент и не завершил подзадачу. Если подзадача уже решена — "
                       "вызови finish_subtask. Если для решения нужен инструмент — вызови его."
        })
        return {"chat": state["chat"] + nudge}

    def handle_finish_node(state) -> Dict[str, Any]:
        last = state["chat"][-1]
        calls = last.tool_calls or []
        finish_call = next((c for c in calls if c["function"]["name"] == "finish_subtask"), None)

        if finish_call:
            args = _tool_args(finish_call)
            status = args.get("status", "failed")
            result = args.get("result", "")
            reason = args.get("reason", "")
        else:
            status, result, reason = "failed", last.content, "достигнут лимит шагов подзадачи"

        return {"subtask_status": status, "subtask_result": result, "subtask_reason": reason}

    def route_finish(state) -> Any:
        if state["subtask_status"] == "success":
            return "summarizer"
        if state["subtask_revisions"] >= MAX_SUBTASK_REVISIONS:
            return "summarizer"
        return "retry"

    def retry_node(state) -> Dict[str, Any]:
        feedback = LLMMessage.from_message({
            "role": "user",
            "content": f"Предыдущая попытка решить подзадачу не удалась. Причина: "
                       f"{state.get('subtask_reason') or 'не указана'}. Попробуй другой подход и снова вызови "
                       f"finish_subtask, когда закончишь."
        })
        return {"chat": state["chat"] + feedback, "subtask_revisions": state["subtask_revisions"] + 1}

    chain_summarizer = (
        ExecEffect({
            "model": lambda d: f"Суммаризатор ({d['summarizer_model']})",
            "on_start_message": lambda d: d["on_start_message"]
            }
            | ExecLambda(lambda d: d["on_start_message"](d["model"]))
        )
        | ExecUpdate(
            summary_chat=(
                ExecUpdate(
                    summary_chat=(lambda d: d["chat"] + LLMChat([{"role": "system", "content": d["summarizer_prompt"]}]))
                )
                | ExecSelect(
                    chat="summary_chat",
                    model="summarizer_model",
                    on_chunk_think="on_think",
                    on_chunk_content="on_content",
                    num_ctx="num_ctx_summarizer"
                )
                | ExecMultiargument(client)
            )
        )
        | ExecEffect({
                        "message": lambda d: d["summary_chat"][-1],
                        "model": lambda d: f"Суммаризатор ({d['summarizer_model']})",
                        "on_end_message": lambda d: d["on_end_message"]
                     }
                     | ExecEffect(lambda d: print(f"\n\n{d['model']} --- ", end=""))
                     | ExecLambda(lambda d: d["on_end_message"](d["message"]))
        )
        | {
            "summaries": lambda d: d["summaries"] + [{
                "index": d["subtask_index"],
                "description": d["plan"][d["subtask_index"]]["description"],
                "status": d["subtask_status"],
                "summary": d["summary_chat"][-1].content,
            }],
            "subtask_index": lambda d: d["subtask_index"] + 1,
        }
    )

    def route_after_summary(state) -> Any:
        if state["subtask_index"] < len(state["plan"]):
            return "dispatch"
        return "finalize"

    chain_finalize = (
        ExecEffect({
            "model": lambda d: f"Финализатор ({d['finalizer_model']})",
            "on_start_message": lambda d: d["on_start_message"]
            }
            | ExecLambda(lambda d: d["on_start_message"](d["model"]))
        )
        | ExecUpdate(
            final_chat=(
                ExecUpdate(
                    final_chat=(lambda d: LLMChat([
                        {"role": "system", "content": d["finalizer_prompt"]},
                        {"role": "user", "content":
                            f"Исходный запрос пользователя: {d['user_message']}\n\n"
                            f"План решения:\n{_format_plan(d['plan'])}\n\n"
                            f"Сводки по подзадачам:\n{_format_summaries(d['summaries'])}"},
                    ]))
                )
                | ExecSelect(
                    chat="final_chat",
                    model="finalizer_model",
                    on_chunk_think="on_think",
                    on_chunk_content="on_content",
                    num_ctx="num_ctx_finalizer"
                )
                | ExecMultiargument(client)
            )
        )
        | ExecEffect({
                        "message": lambda d: d["final_chat"][-1],
                        "model": lambda d: f"Финализатор ({d['finalizer_model']})",
                        "on_end_message": lambda d: d["on_end_message"]
                     }
                     | ExecEffect(lambda d: print(f"\n\n{d['model']} --- ", end=""))
                     | ExecLambda(lambda d: d["on_end_message"](d["message"]))
        )
        | {"answer": lambda d: d["final_chat"][-1].content}
    )

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
                     | ExecEffect(lambda d: print(f"\n\n{d['model']} --- ", end=""))
                     | ExecLambda(lambda d: d["on_end_message"](d["message"]))
        )
        | ExecEffect(lambda d: d["on_title"](d["chat"][-1].content))
        | {"title": lambda d: d["chat"][-1].content}
    )

    return (AgentGraph()
            .add_node("start", lambda s: {})
            .add_node("planner", chain_planner)
            .add_node("namer", chain_namer)
            .add_node("dispatch", dispatch_node)
            .add_node("executor", chain_executor)
            .add_node("toolNode", tool_node)
            .add_node("remind", remind_node)
            .add_node("handle_finish", handle_finish_node)
            .add_node("retry", retry_node)
            .add_node("summarizer", chain_summarizer)
            .add_node("finalize", chain_finalize)
            .set_entry("start")
            .add_edge("start", "planner", "namer")
            .add_edge("namer", END)
            .add_edge("planner", "dispatch")
            .add_edge("dispatch", "executor")
            .add_conditional_edge("executor", route_executor)
            .add_edge("toolNode", "executor")
            .add_edge("remind", "executor")
            .add_conditional_edge("handle_finish", route_finish)
            .add_edge("retry", "executor")
            .add_conditional_edge("summarizer", route_after_summary)
            .add_edge("finalize", END))


def _build_plan(d: Dict[str, Any]) -> Dict[str, Any]:
    last = d["plan_chat"][-1]
    calls = last.tool_calls or []
    submit_call = next((c for c in calls if c["function"]["name"] == "submit_plan"), None)

    subtasks_raw = []
    if submit_call:
        args = _tool_args(submit_call)
        subtasks_raw = args.get("subtasks") or []

    plan = []
    for st in subtasks_raw:
        group = st.get("group") or DEFAULT_GROUP
        tier = st.get("tier") if st.get("tier") in ("low", "high") else "high"
        if ModelSpec.get(group, tier) is None:
            print(f"[предупреждение] неизвестная группа моделей '{group}', использую '{DEFAULT_GROUP}'")
            group = DEFAULT_GROUP
        plan.append({"description": st.get("description", ""), "group": group, "tier": tier})

    if not plan:
        plan = [{"description": d["user_message"], "group": DEFAULT_GROUP, "tier": "high"}]

    return {"plan": plan, "subtask_index": 0, "summaries": []}


EXECUTOR_PROMPT = (
    "Ты ассистент, который решает одну подзадачу из плана декомпозиции более крупной задачи пользователя. Во "
    "время работы ты можешь пользоваться любыми предоставленными тебе инструментами для того, чтобы решить "
    "подзадачу, а также при необходимости писать python-код и запускать его с помощью соответствующих "
    "инструментов. Всегда проверяй факты с помощью поиска в интернете, а также если возникают проблемы с "
    "использованием API, библиотек и т.д. — также обращайся за помощью в интернет. Сосредоточься только на своей "
    "текущей подзадаче — остальные подзадачи решат другие вызовы модели.\n\n"
    "Прежде чем решить, что для подзадачи не хватает данных, попробуй получить их самостоятельно с помощью "
    "доступных инструментов — почти любые недостающие данные можно добыть кодом или поиском. Например: "
    "геолокацию/город пользователя можно определить по IP (запросом к geo-API из run_python или через "
    "web_search/fetch_url), курсы валют, погоду, время и подобные факты — через открытые API или поиск. Не "
    "останавливайся и не сдавайся после первой неудачи — пробуй другой инструмент или другой подход. Инструмент "
    "ask_user для вопроса пользователю используй только в самом крайнем случае, когда информацию объективно "
    "нельзя получить инструментами (например, личные предпочтения или решения, которые знает только сам "
    "пользователь).\n\n"
    "У fetch_url, fetch_url_render, run_bash и run_python есть параметр limit — по умолчанию он небольшой, "
    "чтобы не раздувать контекст без необходимости. Если знаешь, что тебе нужен весь вывод (большой JSON, "
    "длинный лог, полный файл и т.п.) — смело увеличивай limit (до 20000), не бойся его поднимать, когда это "
    "оправдано задачей. Но для веб-страниц старайся сначала брать данные из компактных API с JSON-ответом, а не "
    "с полных HTML-страниц сайтов с большим количеством лишней вёрстки — так меньше шансов, что нужное обрежется.\n\n"
    "Если для подзадачи нужно вызвать несколько независимых инструментов (например, проверить два разных "
    "источника, или запросить данные по нескольким городам) — вызови их все одним сообщением, а не по очереди "
    "в отдельных ходах. Каждый лишний ход пересылает модели всю накопленную историю подзадачи заново, поэтому "
    "меньше ходов — меньше потраченных токенов.\n\n"
    "run_bash и run_python выполняются в реальной файловой системе Windows этой машины — не предполагай заранее "
    "путей вроде /home/user или иной типичной Linux-структуры, их здесь нет. Если нужно сохранить файл (например, "
    "Excel/CSV), сначала узнай текущую рабочую директорию (pwd в run_bash или os.getcwd() в run_python) и сохраняй "
    "туда же относительным путём, либо явно укажи путь, который сам только что проверил."
)

NAMER_PROMPT = (
    "Ты не должен выполнять запрос пользователя и отвечать на его вопросы. Твоя единстенная задача - придумать "
    "очень короткое название для последующей беседы (3 - 5 слова) по первому запросу пользователя. Ответь только "
    "названием, ничего лишнего."
)

SUMMARIZER_PROMPT = (
    "Сделай краткую сводку того, что было сделано в этом диалоге при решении подзадачи: какие действия "
    "предприняты, какие инструменты вызывались, какой получен результат, какие важные факты, пути, значения, "
    "ссылки или идентификаторы были обнаружены. Сводка должна быть компактной, но обязана сохранить все "
    "конкретные детали, которые могут понадобиться при решении следующих подзадач. Ответь только текстом сводки, "
    "без вступлений."
)

FINALIZER_PROMPT = (
    "Ты должен собрать финальный ответ пользователю на основе плана решения его задачи и сводок по всем "
    "подзадачам. Ответ должен быть связным, полным и напрямую отвечать на исходный запрос пользователя, без "
    "упоминания внутреннего устройства решения (плана, подзадач, сводок и т.д.)."
)


def _planner_prompt() -> str:
    groups_text = "\n".join(f"- {g}: {desc}" for g, desc in GROUP_DESCRIPTIONS.items())
    return (
        "Ты — планировщик. Твоя задача разбить запрос пользователя на последовательность конкретных подзадач и "
        "для каждой подзадачи выбрать наиболее подходящую группу моделей и уровень сложности. Не решай саму "
        "задачу — верни план, вызвав инструмент submit_plan. Каждая подзадача должна быть самодостаточной и "
        "понятной без остального контекста беседы, так как исполнитель подзадачи не увидит переписку целиком, "
        "только сводки предыдущих подзадач. Если задача простая — сделай план из одной подзадачи.\n\n"
        f"Доступные группы моделей:\n{groups_text}\n\n"
        "Уровень (tier) выбирай не по формальной 'сложности', а по тому, насколько заранее предсказуем путь "
        "решения:\n"
        "- 'low' — подзадача с очевидным, заранее понятным способом решения: простое форматирование, "
        "вычисление, пересказ уже известных данных, вызов одного конкретного инструмента без выбора между "
        "вариантами.\n"
        "- 'high' — подзадача, где неизвестно заранее, какой инструмент/подход сработает, нужно перебирать "
        "варианты, принимать решения по ходу дела или есть риск, что первый способ не сработает (например, "
        "определить что-то по внешним источникам, когда неясно, какой API/сайт отдаст нужные данные). Слабая "
        "модель на такой подзадаче будет долго колебаться и метаться между попытками, тратя намного больше "
        "токенов, чем сразу решила бы сильная модель — при сомнении ставь 'high'."
    )


class _RunStats:
    """Черновая статистика на весь прогон агента (токены, время по стадиям) — только для отладки/тестов."""

    def __init__(self):
        self._lock = threading.Lock()
        self.prompt_tokens = 0
        self.response_tokens = 0
        self.load_duration = 0      # наносекунды
        self.prompt_duration = 0    # наносекунды, "рефил"
        self.response_duration = 0  # наносекунды, генерация

    def add(self, message: LLMMessage):
        with self._lock:
            if message.tokens:
                self.prompt_tokens += message.tokens.prompt or 0
                self.response_tokens += message.tokens.response or 0
            if message.duration:
                self.load_duration += message.duration.load or 0
                self.prompt_duration += message.duration.prompt or 0
                self.response_duration += message.duration.response or 0

    def wrap(self, client: LLMClient) -> LLMClient:
        original_stream = client.stream

        def counting_stream(chat, on_chunk_think=None, on_chunk_content=None, **kwargs):
            result = original_stream(chat, on_chunk_think=on_chunk_think, on_chunk_content=on_chunk_content, **kwargs)
            self.add(result[-1])
            return result

        client.stream = counting_stream
        return client


def agent_logic(
        user_message: str,
        error_text: str = "",
        on_think: Optional[Callable[[str], Any]] = None,
        on_content: Optional[Callable[[str], Any]] = None,
        on_title: Optional[Callable[[str], Any]] = None,
        on_tool: Optional[Callable[[Dict[str, Any]], Any]] = None,
        on_end_message: Optional[Callable[[Dict[str, Any]], Any]] = None,
        on_start_message: Optional[Callable[[Dict[str, Any]], Any]] = None
):
    client = OllamaClient(url=OLLAMA_URL)
    stats = _RunStats()
    stats.wrap(client)
    agent = create_agent(client)
    started_at = time.perf_counter()

    initial = AgentState({
        "chat": LLMChat([{"role": "user", "content": user_message}]),
        "user_message": user_message,

        "planner_model": PLANNER_MODEL,
        "namer_model": NAMER_MODEL,
        "summarizer_model": SUMMARIZER_MODEL,
        "finalizer_model": FINALIZER_MODEL,

        "planner_prompt": _planner_prompt(),
        "namer_prompt": NAMER_PROMPT,
        "summarizer_prompt": SUMMARIZER_PROMPT,
        "finalizer_prompt": FINALIZER_PROMPT,
        "executor_prompt": EXECUTOR_PROMPT,

        "planner_tools": [SUBMIT_PLAN_TOOL],
        "executor_tools": tools_spec() + [FINISH_SUBTASK_TOOL],

        "on_think": on_think,
        "on_content": on_content,
        "on_title": on_title,
        "on_tool": on_tool,
        "on_end_message": on_end_message,
        "on_start_message": on_start_message,

        "num_ctx_planner": NUM_CTX_PLANNER,
        "num_ctx_namer": NUM_CTX_NAMER,
        "num_ctx_executor": NUM_CTX_EXECUTOR,
        "num_ctx_summarizer": NUM_CTX_SUMMARIZER,
        "num_ctx_finalizer": NUM_CTX_FINALIZER,
    })

    final = agent.stream(initial)

    elapsed = time.perf_counter() - started_at
    total_tokens = stats.prompt_tokens + stats.response_tokens
    total_duration = stats.load_duration + stats.prompt_duration + stats.response_duration
    print(
        f"\n\nОбщее время работы агента: {elapsed:.2f} с\n"
        f"Время по стадиям (сумма по всем вызовам моделей, из них {total_duration / 1e9:.2f} с):\n"
        f"\tЗагрузка: {stats.load_duration / 1e9:.2f} с\n"
        f"\tРефил: {stats.prompt_duration / 1e9:.2f} с\n"
        f"\tГенерация: {stats.response_duration / 1e9:.2f} с\n"
        f"Токены: промпт={stats.prompt_tokens}, генерация={stats.response_tokens}, всего={total_tokens}"
    )

    return final
