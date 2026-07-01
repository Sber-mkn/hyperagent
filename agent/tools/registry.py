"""Реестр инструментов и декоратор @tool.

Инструмент — обычная функция, помеченная @tool. Декоратор регистрирует её в
глобальном реестре и САМ достаёт информацию из docstring:
  - краткое описание (текст до секции Args) -> description инструмента;
  - секция параметров (Google `Args:` или reST `:param name:`) -> описания
    параметров в JSON-схеме; типы параметров берутся из аннотаций.
Возвращает исходную функцию — её по-прежнему можно звать напрямую.
"""
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


@dataclass
class Tool:
    name: str
    description: str
    func: Callable[..., Any]
    parameters: Dict[str, Any]                    # JSON-schema объекта параметров

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


def _build_schema(func: Callable[..., Any], param_docs: Dict[str, str]) -> Dict[str, Any]:
    props: Dict[str, Any] = {}
    required: List[str] = []
    for pname, p in inspect.signature(func).parameters.items():
        prop: Dict[str, Any] = {"type": _JSON_TYPES.get(p.annotation, "string")}
        if pname in param_docs:
            prop["description"] = param_docs[pname]
        props[pname] = prop
        if p.default is inspect.Parameter.empty:
            required.append(pname)
    return {"type": "object", "properties": props, "required": required}


def tool(_func: Optional[Callable] = None, *,
         name: Optional[str] = None,
         description: Optional[str] = None,
         parameters: Optional[Dict[str, Any]] = None):
    """Декоратор. Использование: @tool (всё берётся из docstring) либо
    @tool(name=..., description=..., parameters=...) для явного переопределения."""
    def deco(func: Callable[..., Any]) -> Callable[..., Any]:
        doc_summary, param_docs = _parse_docstring(func.__doc__)
        t = Tool(
            name=name or func.__name__,
            description=description or doc_summary,
            func=func,
            parameters=parameters or _build_schema(func, param_docs),
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


def run_tool_calls(calls: List[Dict[str, Any]]) -> List[tuple]:
    """Выполнить список tool-call'ов, вернуть [(name, result), ...].
    Несколько вызовов идут параллельно (потоки — инструменты I/O-bound)."""
    def one(call: Dict[str, Any]) -> tuple:
        fn = call.get("function", call)
        name = fn["name"]
        args = _normalize_args(fn.get("arguments"))
        try:
            return name, get_tool(name)(**args)
        except Exception as e:                    # ошибка инструмента -> модель сможет исправиться
            return name, f"[ошибка инструмента {name}: {e}]"

    calls = list(calls or [])
    if len(calls) <= 1:
        return [one(c) for c in calls]
    with ThreadPoolExecutor(max_workers=len(calls)) as pool:
        return list(pool.map(one, calls))
