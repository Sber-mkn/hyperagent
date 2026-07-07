"""Tool registry — adapted from llm_without_frameworks_llama branch."""

import inspect
import json
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

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
    r"^(args|arguments|parameters|params|returns?|raises|yields|examples?|notes?)\s*:\s*$",
    re.I,
)
_GOOGLE_PARAM = re.compile(r"^(\w+)\s*(?:\([^)]*\))?\s*:\s*(.*)$")
_SPHINX_PARAM = re.compile(r"^:param\s+(?:\w+\s+)?(\w+)\s*:\s*(.*)$")


@dataclass
class Tool:
    name: str
    description: str
    func: Callable[..., Any]
    parameters: Dict[str, Any]

    def __call__(self, **kwargs: Any) -> Any:
        return self.func(**kwargs)


_REGISTRY: Dict[str, Tool] = {}


def _parse_docstring(doc: Optional[str]) -> Tuple[str, Dict[str, str]]:
    doc = inspect.cleandoc(doc or "")
    if not doc:
        return "", {}

    lines = doc.splitlines()
    params: Dict[str, str] = {}
    summary: List[str] = []
    i, n = 0, len(lines)

    while i < n:
        line = lines[i].strip()
        m = _SPHINX_PARAM.match(line)
        if m:
            params[m.group(1)] = m.group(2).strip()
            i += 1
            continue
        if _ARG_HDR.match(line):
            i += 1
            base_indent: Optional[int] = None
            last: Optional[str] = None
            while i < n:
                raw = lines[i]
                s = raw.strip()
                if not s:
                    i += 1
                    continue
                if _SECTION.match(s):
                    break
                indent = len(raw) - len(raw.lstrip())
                if base_indent is None:
                    base_indent = indent
                pm = _GOOGLE_PARAM.match(s)
                if pm and indent <= base_indent:
                    params[pm.group(1)] = pm.group(2).strip()
                    last = pm.group(1)
                    i += 1
                elif last is not None:
                    params[last] = (params[last] + " " + s).strip()
                    i += 1
                else:
                    break
            continue
        if line.startswith(":") or _SECTION.match(line):
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


def tool(_func: Optional[Callable] = None, *, name: Optional[str] = None,
         description: Optional[str] = None, parameters: Optional[Dict[str, Any]] = None):
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


_ARG_ALIASES: Dict[str, Dict[str, str]] = {
    "write_file": {"file_path": "path", "filename": "path", "contents": "content", "text": "content"},
    "read_file": {"file_path": "path", "filename": "path"},
    "run_python": {"path": "file_path", "filename": "file_path"},
    "change_file": {"file_path": "path", "filename": "path"},
}


def _normalize_args(args: Any, tool_name: str = "") -> Dict[str, Any]:
    if isinstance(args, str):
        args = json.loads(args or "{}")
    normalized = dict(args or {})
    aliases = _ARG_ALIASES.get(tool_name, {})
    for alias, canonical in aliases.items():
        if alias in normalized and canonical not in normalized:
            normalized[canonical] = normalized.pop(alias)
    return normalized


def run_tool_calls(calls: List[Dict[str, Any]]) -> List[tuple[str, str, str | None]]:
    """Return list of (name, result, tool_call_id)."""

    def one(call: Dict[str, Any]) -> tuple[str, str, str | None]:
        fn = call.get("function", call)
        name = fn["name"]
        args = _normalize_args(fn.get("arguments"), name)
        call_id = call.get("id")
        try:
            return name, str(get_tool(name)(**args)), call_id
        except Exception as e:
            return name, f"ERROR in {name}: {e}", call_id

    calls = list(calls or [])
    if len(calls) <= 1:
        return [one(c) for c in calls]
    with ThreadPoolExecutor(max_workers=len(calls)) as pool:
        return list(pool.map(one, calls))
