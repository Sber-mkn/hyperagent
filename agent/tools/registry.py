import inspect
import json
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

_JSON_TYPES = {
    str: "string", int: "integer", float: "number",
    bool: "boolean", list: "array", dict: "object",
}

_ARG_HDR = re.compile(r'^(args|arguments|parameters|params)\s*:\s*$', re.I)
_SECTION = re.compile(r'^(args|arguments|parameters|params|returns?|raises|yields|examples?|notes?)\s*:\s*$', re.I)
_GOOGLE_PARAM = re.compile(r'^(\w+)\s*(?:\([^)]*\))?\s*:\s*(.*)$')      # name: desc  |  name (type): desc
_SPHINX_PARAM = re.compile(r'^:param\s+(?:\w+\s+)?(\w+)\s*:\s*(.*)$')  # :param name: desc


on_command: Optional[Callable[[dict[str, Any]], Any]] = None
# UI-specific hook for ask_user: whichever client is actually running (GUI or
# console) wires this to something that can reach the real human, since a
# plain input() has no interactive stdin to read in a GUI process. Left
# unset, ask_user falls back to input() (e.g. a bare "python -m agent.main").
on_ask_user: Optional[Callable[[str], str]] = None
# True only inside the agent's own process (set by agent_immutable/main.py
# alongside on_command) -- never true in the client process, even though both
# run the exact same agent.tools code. Lets a tool whose call can land on
# either side (run_bash/run_powershell/run_python) tell, from inside its own
# function body, which side it is actually executing on right now.
running_on_server: bool = False


@dataclass
class Tool:
    name: str
    description: str
    func: Callable[..., Any]
    parameters: Dict[str, Any]                    # JSON-schema объекта параметров
    default_target: str = "server"                # куда роутится вызов, если модель не указала target явно
    allowed_targets: frozenset = frozenset({"server"})  # весь набор допустимых target для этого инструмента

    def __call__(self, **kwargs: Any) -> Any:
        return self.func(**kwargs)


_REGISTRY: Dict[str, Tool] = {}


def _parse_docstring(doc: Optional[str]) -> Tuple[str, Dict[str, str]]:
    """Вернуть (краткое описание, {параметр: описание}) из docstring."""
    doc = inspect.cleandoc(doc or "")
    if not doc:
        return "", {}

    lines = doc.splitlines()
    params: Dict[str, str] = {}
    summary: List[str] = []
    i, n = 0, len(lines)

    while i < n:
        line = lines[i].strip()

        m = _SPHINX_PARAM.match(line)             # reST: :param name: ...
        if m:
            params[m.group(1)] = m.group(2).strip()
            i += 1
            continue

        if _ARG_HDR.match(line):                  # Google: Args:
            i += 1
            base_indent: Optional[int] = None
            last: Optional[str] = None
            while i < n:
                raw = lines[i]
                s = raw.strip()
                if not s:
                    i += 1
                    continue
                if _SECTION.match(s):             # началась следующая секция
                    break
                indent = len(raw) - len(raw.lstrip())
                if base_indent is None:
                    base_indent = indent
                pm = _GOOGLE_PARAM.match(s)
                if pm and indent <= base_indent:
                    params[pm.group(1)] = pm.group(2).strip()
                    last = pm.group(1)
                    i += 1
                elif last is not None:            # продолжение описания параметра
                    params[last] = (params[last] + " " + s).strip()
                    i += 1
                else:
                    break
            continue

        if line.startswith(":") or _SECTION.match(line):   # прочие поля/секции — не в summary
            i += 1
            continue

        summary.append(line)
        i += 1

    return " ".join(x for x in summary if x).strip(), params


TARGET_PARAM = "target"
DEFAULT_TARGET = "server"


def _build_schema(
        func: Callable[..., Any],
        param_docs: Dict[str, str],
        default_target: str = "server",
        allowed_targets: frozenset = frozenset({"server"}),
) -> Dict[str, Any]:
    props: Dict[str, Any] = {}
    required: List[str] = []
    for pname, p in inspect.signature(func).parameters.items():
        prop: Dict[str, Any] = {"type": _JSON_TYPES.get(p.annotation, "string")}
        if pname in param_docs:
            prop["description"] = param_docs[pname]
        props[pname] = prop
        if p.default is inspect.Parameter.empty:
            required.append(pname)
    # A tool locked to a single target has nothing to choose -- no "target"
    # property is exposed. A tool allowed on more than one target exposes it
    # so the model can pick, defaulting to default_target if omitted.
    if len(allowed_targets) > 1:
        props[TARGET_PARAM] = {
            "type": "string",
            "enum": sorted(allowed_targets),
            "description": (
                f"Где выполнить инструмент (по умолчанию '{default_target}'): 'server' — в контейнере "
                "агента, 'client' — на машине пользователя, запустившей клиент."
            ),
        }
    return {"type": "object", "properties": props, "required": required}


_TARGET_NOTE = {
    "server": "[Выполняется на сервере, в контейнере агента.]",
    "client": "[Выполняется на компьютере пользователя, запустившего клиент.]",
}


def _describe_target(description: str, default_target: str, allowed_targets: frozenset) -> str:
    if len(allowed_targets) > 1:
        note = (
            f"[Может выполняться и на сервере (в контейнере агента), и на клиенте (на машине "
            f"пользователя) — выбирается параметром target, по умолчанию '{default_target}'.]"
        )
    else:
        note = _TARGET_NOTE.get(default_target, f"[Выполняется на: {default_target}.]")
    return f"{description} {note}".strip()


def tool(_func: Optional[Callable] = None, *,
         name: Optional[str] = None,
         description: Optional[str] = None,
         parameters: Optional[Dict[str, Any]] = None,
         default_target: str = "server",
         allowed_targets: Optional[Tuple[str, ...]] = None):
    """Декоратор. Использование: @tool (всё берётся из docstring) либо
    @tool(name=..., description=..., parameters=..., default_target=..., allowed_targets=...)
    для явного переопределения.
    default_target — куда роутится вызов, если модель не указала target явно (или если инструмент
    вообще не выбирает target — тогда это единственное место, где он выполняется).
    allowed_targets — весь набор допустимых target для инструмента; по умолчанию это только
    {default_target} (инструмент жёстко привязан к одному месту, модель это не выбирает). Передай
    allowed_targets=("server", "client"), чтобы модель могла выбирать target для каждого вызова —
    используется для run_bash/run_powershell/run_python, у которых оба места осмысленны.
    Набор allowed_targets автоматически дописывается в конец description, которое видит модель,
    так что описание инструмента не может разойтись с тем, где он реально может выполняться."""
    def deco(func: Callable[..., Any]) -> Callable[..., Any]:
        doc_summary, param_docs = _parse_docstring(func.__doc__)
        targets = frozenset(allowed_targets) if allowed_targets else frozenset({default_target})
        t = Tool(
            name=name or func.__name__,
            description=_describe_target(description or doc_summary, default_target, targets),
            func=func,
            parameters=parameters or _build_schema(func, param_docs, default_target, targets),
            default_target=default_target,
            allowed_targets=targets,
        )
        _REGISTRY[t.name] = t
        return func
    return deco(_func) if _func is not None else deco


def get_tool(name: str) -> Tool:
    return _REGISTRY[name]


def all_tools() -> List[Tool]:
    return list(_REGISTRY.values())


def tools_spec() -> List[Dict[str, Any]]:
    """Список схем в формате function-calling (Ollama/OpenAI)."""
    return [
        {"type": "function", "function": {
            "name": t.name, "description": t.description, "parameters": t.parameters,
        }}
        for t in _REGISTRY.values()
    ]


def _normalize_args(args: Any) -> Dict[str, Any]:
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


def tool_target(call: Dict[str, Any]) -> str:
    """Куда выполнить вызов. Для инструмента, жёстко привязанного к одному месту
    (allowed_targets содержит один элемент), это всегда его default_target — схема
    вообще не содержит поля target, так что если оно всё же где-то возникло (например,
    из старой истории), оно игнорируется. Для инструмента с несколькими allowed_targets
    (run_bash/run_powershell/run_python) уважается явный target из аргументов модели,
    если он входит в allowed_targets; иначе используется default_target."""
    fn = call.get("function", call)
    registered = _REGISTRY.get(fn.get("name"))
    if registered is None:
        return DEFAULT_TARGET
    args = _normalize_args(fn.get("arguments"))
    explicit = args.get(TARGET_PARAM)
    if explicit and explicit in registered.allowed_targets:
        return explicit
    return registered.default_target


def execute_tool(call: Dict[str, Any]) -> tuple:
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


def run_tool_calls(calls: List[Dict[str, Any]]) -> List[tuple]:
    """Выполнить список tool-call'ов, вернуть [(name, result), ...].
    Несколько вызовов идут параллельно (потоки — инструменты I/O-bound)."""
    calls = list(calls or [])
    if len(calls) <= 1:
        return [execute_tool(c) for c in calls]
    with ThreadPoolExecutor(max_workers=len(calls)) as pool:
        return list(pool.map(execute_tool, calls))
