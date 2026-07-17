import inspect
import json
import re
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

_JSON_TYPES = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    list: "array",
    dict: "object",
}

_ARG_HDR = re.compile(r"^(args|arguments|parameters|params)\s*:\s*$", re.I)
_SECTION = re.compile(
    r"^(args|arguments|parameters|params|returns?|raises|yields|examples?|notes?)\s*:\s*$", re.I
)
_GOOGLE_PARAM = re.compile(
    r"^(\w+)\s*(?:\([^)]*\))?\s*:\s*(.*)$"
)  # name: desc  |  name (type): desc
_SPHINX_PARAM = re.compile(r"^:param\s+(?:\w+\s+)?(\w+)\s*:\s*(.*)$")  # :param name: desc


on_command: Callable[[dict[str, Any]], Any] | None = None
# UI-specific hook for ask_user: whichever client is actually running (GUI or
# console) wires this to something that can reach the real human, since a
# plain input() has no interactive stdin to read in a GUI process. Left
# unset, ask_user falls back to input() (e.g. a bare "python -m agent.main").
on_ask_user: Callable[[str], str] | None = None


@dataclass
class Tool:
    name: str
    description: str
    func: Callable[..., Any]
    parameters: dict[str, Any]  # JSON-schema объекта параметров
    default_target: str = "server"  # куда всегда роутится вызов этого инструмента (фиксировано)

    def __call__(self, **kwargs: Any) -> Any:
        return self.func(**kwargs)


_REGISTRY: dict[str, Tool] = {}


def _parse_docstring(doc: str | None) -> tuple[str, dict[str, str]]:
    """Вернуть (краткое описание, {параметр: описание}) из docstring."""
    doc = inspect.cleandoc(doc or "")
    if not doc:
        return "", {}

    lines = doc.splitlines()
    params: dict[str, str] = {}
    summary: list[str] = []
    i, n = 0, len(lines)

    while i < n:
        line = lines[i].strip()

        m = _SPHINX_PARAM.match(line)  # reST: :param name: ...
        if m:
            params[m.group(1)] = m.group(2).strip()
            i += 1
            continue

        if _ARG_HDR.match(line):  # Google: Args:
            i += 1
            base_indent: int | None = None
            last: str | None = None
            while i < n:
                raw = lines[i]
                s = raw.strip()
                if not s:
                    i += 1
                    continue
                if _SECTION.match(s):  # началась следующая секция
                    break
                indent = len(raw) - len(raw.lstrip())
                if base_indent is None:
                    base_indent = indent
                pm = _GOOGLE_PARAM.match(s)
                if pm and indent <= base_indent:
                    params[pm.group(1)] = pm.group(2).strip()
                    last = pm.group(1)
                    i += 1
                elif last is not None:  # продолжение описания параметра
                    params[last] = (params[last] + " " + s).strip()
                    i += 1
                else:
                    break
            continue

        if line.startswith(":") or _SECTION.match(line):  # прочие поля/секции — не в summary
            i += 1
            continue

        summary.append(line)
        i += 1

    return " ".join(x for x in summary if x).strip(), params


TARGET_PARAM = "target"
DEFAULT_TARGET = "server"


def _build_schema(
    func: Callable[..., Any], param_docs: dict[str, str], default_target: str = "server"
) -> dict[str, Any]:
    props: dict[str, Any] = {}
    required: list[str] = []
    for pname, p in inspect.signature(func).parameters.items():
        prop: dict[str, Any] = {"type": _JSON_TYPES.get(p.annotation, "string")}
        if pname in param_docs:
            prop["description"] = param_docs[pname]
        props[pname] = prop
        if p.default is inspect.Parameter.empty:
            required.append(pname)
    # Where a tool runs is fixed per-tool (see Tool.default_target), not a
    # model choice -- no "target" property is exposed here.
    return {"type": "object", "properties": props, "required": required}


_TARGET_NOTE = {
    "server": "[Выполняется на сервере, в контейнере агента.]",
    "client": "[Выполняется на компьютере пользователя, запустившего клиент.]",
}


def _describe_target(description: str, default_target: str) -> str:
    note = _TARGET_NOTE.get(default_target, f"[Выполняется на: {default_target}.]")
    return f"{description} {note}".strip()


def tool(
    _func: Callable | None = None,
    *,
    name: str | None = None,
    description: str | None = None,
    parameters: dict[str, Any] | None = None,
    default_target: str = "server",
):
    """Декоратор. Использование: @tool (всё берётся из docstring) либо
    @tool(name=..., description=..., parameters=..., default_target=...) для явного переопределения.
    default_target фиксирует, где инструмент ВСЕГДА выполняется — 'server' (в контейнере агента) или
    'client' (на машине пользователя, запустившей клиент); модель этот выбор изменить не может.
    Это же место (server/client) автоматически дописывается в конец description, которое видит модель,
    так что описание одиночного инструмента не может разойтись с тем, где он реально выполняется."""

    def deco(func: Callable[..., Any]) -> Callable[..., Any]:
        doc_summary, param_docs = _parse_docstring(func.__doc__)
        t = Tool(
            name=name or func.__name__,
            description=_describe_target(description or doc_summary, default_target),
            func=func,
            parameters=parameters or _build_schema(func, param_docs, default_target),
            default_target=default_target,
        )
        _REGISTRY[t.name] = t
        return func

    return deco(_func) if _func is not None else deco


def get_tool(name: str) -> Tool:
    return _REGISTRY[name]


def all_tools() -> list[Tool]:
    return list(_REGISTRY.values())


def tools_spec() -> list[dict[str, Any]]:
    """Список схем в формате function-calling (Ollama/OpenAI)."""
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
            },
        }
        for t in _REGISTRY.values()
    ]


def _normalize_args(args: Any) -> dict[str, Any]:
    if isinstance(args, str):
        args = json.loads(args or "{}")
    return dict(args or {})


def truncate_middle(text: str, max_chars: int) -> str:
    """Обрезать текст до max_chars, сохраняя начало и конец (нужное часто оказывается либо в начале,
    либо в хвосте — например, таблица данных после навигационного меню сайта)."""
    if len(text) <= max_chars:
        return text
    head = max_chars // 2
    tail = max_chars - head
    cut = len(text) - head - tail
    return f"{text[:head]}\n...[обрезано {cut} символов]...\n{text[-tail:]}"


def tool_target(call: dict[str, Any]) -> str:
    """Куда выполнить вызов — это свойство самого инструмента (см. Tool.default_target),
    не выбор модели: схема инструмента не содержит поля target, так что откуда бы такое
    поле ни взялось в вызове (например, из старой истории), оно игнорируется."""
    fn = call.get("function", call)
    registered = _REGISTRY.get(fn.get("name"))
    return registered.default_target if registered else DEFAULT_TARGET


def execute_tool(call: dict[str, Any]) -> tuple:
    fn = call.get("function", call)
    name = fn["name"]
    args = _normalize_args(fn.get("arguments"))
    args.pop(TARGET_PARAM, None)
    try:
        return name, get_tool(name)(**args)
    except Exception as e:
        return name, f"[ошибка инструмента {name}: {e}]"


def execute_tool_from_json(call: str) -> tuple:
    fn = json.loads(call).get("command")
    name = fn["name"]
    args = _normalize_args(fn.get("arguments"))
    args.pop(TARGET_PARAM, None)
    try:
        return name, get_tool(name)(**args)
    except Exception as e:
        return name, f"[ошибка инструмента {name}: {e}]"


def run_tool_calls(calls: list[dict[str, Any]]) -> list[tuple]:
    """Выполнить список tool-call'ов, вернуть [(name, result), ...].
    Несколько вызовов идут параллельно (потоки — инструменты I/O-bound)."""
    calls = list(calls or [])
    if len(calls) <= 1:
        return [execute_tool(c) for c in calls]
    with ThreadPoolExecutor(max_workers=len(calls)) as pool:
        return list(pool.map(execute_tool, calls))
