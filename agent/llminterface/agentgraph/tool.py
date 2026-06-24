import inspect
from typing import Callable, Optional, Literal, Union, get_type_hints, get_origin, get_args

_PY_TO_JSON = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    list: "array",
    dict: "object"
}


def _json_type(annotation) -> dict:
    """Возвращает часть json-схемы для одного типа"""
    # Обычный тип
    if annotation in _PY_TO_JSON:
        return {"type": _PY_TO_JSON[annotation]}

    origin = get_origin(annotation)

    # Literal -> enum
    if origin is Literal:
        choices = list(get_args(annotation))
        base = type(choices[0]) if choices else str
        return {"type": _PY_TO_JSON.get(base, "string"), "enum": choices}

    # Optional -> значение
    if origin is Union:
        args = [a for a in get_args(annotation) if a is not type(None)]
        if args:
            return _json_type(args[0])

    # list, dict, ...
    if origin in _PY_TO_JSON:
        return {"type": _PY_TO_JSON[origin]}

    return {"type": "string"}


def _parse_param_docs(doc: str) -> dict[str, str]:
    """Парсинг секции Args:/Parameters: из докстринг"""
    result: dict[str, str] = {}
    in_args = False
    for line in doc.splitlines():
        s = line.strip()
        if s.lower() in ("args:", "arguments:", "parameters:"):
            in_args = True
            continue
        if in_args:
            if not s or s.lower().endswith(":") and s[-1] == ":" and " " not in s.rstrip(":"):
                break
            if ":" in s:
                key, _, val = s.partition(":")
                result[key.strip()] = val.strip()

    return result


def agent_tool(
        func: Optional[Callable] = None, *,
        name: Optional[str] = None,
        description: Optional[str] = None
):
    """Декоратор для построения tool_schema из сигнатуры и докстринга функции"""

    def decorator(fn: Callable) -> Callable:
        sig = inspect.signature(fn)
        try:
            hints = get_type_hints(fn)
        except Exception:
            hints = getattr(fn, "__annotations__", {})

        doc = inspect.getdoc(fn) or ""

        tool_name = name or fn.__name__

        tool_desc = description or doc.split("\n\n")[0].split("Args:")[0].strip()
        param_docs = _parse_param_docs(doc)

        properties: dict[str, dict] = {}
        required: list[str] = []

        for p_name, param in sig.parameters.items():
            if p_name in ("self", "cls"):
                continue
            ann = hints.get(p_name, str)
            prop = _json_type(ann)

            if p_name in param_docs:
                prop["description"] = param_docs[p_name]
            properties[p_name] = prop
            if param.default is inspect.Parameter.empty:
                required.append(p_name)

        fn.tool_schema = {
            "type": "function",
            "function": {
                "name": tool_name,
                "description": tool_desc,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required
                }
            }
        }

        fn.tool_name = tool_name
        return fn
    return decorator(func) if func is not None else decorator


def collect_schemas(tools: list[Callable]) -> list[dict]:
    return [t.tool_schema for t in tools]


def collect_tool_map(tools: list[Callable]) -> dict[str, Callable]:
    return {t.tool_name: t for t in tools}


