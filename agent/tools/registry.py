"""Tool registry for the V3 agent."""

from __future__ import annotations

import inspect
import json
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

_JSON_TYPES = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    list: "array",
    dict: "object",
}

# Models sometimes use alternate argument names — map to our parameter names.
_ARG_ALIASES: Dict[str, Dict[str, str]] = {
    "write_file": {
        "file_path": "path",
        "filename": "path",
        "contents": "content",
        "text": "content",
    },
    "read_file": {"file_path": "path", "filename": "path"},
    "run_python": {"path": "file_path", "filename": "file_path"},
}


@dataclass
class Tool:
    name: str
    description: str
    func: Callable[..., Any]
    parameters: Dict[str, Any]

    def __call__(self, **kwargs: Any) -> Any:
        return self.func(**kwargs)


_REGISTRY: Dict[str, Tool] = {}


def _schema(func: Callable[..., Any]) -> Dict[str, Any]:
    props: Dict[str, Any] = {}
    required: List[str] = []
    for pname, p in inspect.signature(func).parameters.items():
        props[pname] = {"type": _JSON_TYPES.get(p.annotation, "string")}
        if p.default is inspect.Parameter.empty:
            required.append(pname)
    return {"type": "object", "properties": props, "required": required}


def tool(
    _func: Optional[Callable] = None,
    *,
    name: Optional[str] = None,
    description: Optional[str] = None,
):
    def deco(func: Callable[..., Any]) -> Callable[..., Any]:
        doc = inspect.cleandoc(func.__doc__ or "")
        summary = doc.splitlines()[0].strip() if doc else ""
        t = Tool(
            name=name or func.__name__,
            description=description or summary,
            func=func,
            parameters=_schema(func),
        )
        _REGISTRY[t.name] = t
        return func

    return deco(_func) if _func is not None else deco


def tools_spec() -> List[Dict[str, Any]]:
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


def _normalize_args(args: Any, tool_name: str = "") -> Dict[str, Any]:
    if isinstance(args, str):
        args = json.loads(args or "{}")
    normalized = dict(args or {})
    for alias, canonical in _ARG_ALIASES.get(tool_name, {}).items():
        if alias in normalized and canonical not in normalized:
            normalized[canonical] = normalized.pop(alias)
    return normalized


def run_tool_calls(calls: List[Dict[str, Any]]) -> List[tuple[str, str, str | None]]:
    """Return list of (name, result, tool_call_id)."""

    def one(call: Dict[str, Any]) -> tuple[str, str, str | None]:
        fn = call.get("function", call)
        name = fn["name"]
        call_id = call.get("id")
        try:
            args = _normalize_args(fn.get("arguments"), name)
        except (json.JSONDecodeError, TypeError, ValueError) as e:
            return name, f"ERROR: invalid JSON in tool arguments for {name}: {e}", call_id
        try:
            return name, str(_REGISTRY[name](**args)), call_id
        except KeyError:
            return name, f"ERROR: unknown tool {name}", call_id
        except Exception as e:
            return name, f"ERROR in {name}: {e}", call_id

    return [one(c) for c in (calls or [])]
