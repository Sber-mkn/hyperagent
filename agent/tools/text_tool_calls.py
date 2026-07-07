"""Parse tool calls that some models emit as XML text instead of structured tool_calls."""

from __future__ import annotations

import json
import re
from typing import Any

_TOOL_MARKERS = ("<tool_call>", "<function=", "<parameter=")


def looks_like_tool_dump(text: str) -> bool:
    sample = (text or "").lower()
    return any(m in sample for m in _TOOL_MARKERS)


def clean_final_answer(text: str) -> str:
    """Drop XML tool blocks from the user-visible answer."""
    text = (text or "").strip()
    if not text:
        return "(no answer produced)"
    if not looks_like_tool_dump(text):
        return text
    lowered = text.lower()
    cut = len(text)
    for marker in _TOOL_MARKERS:
        idx = lowered.find(marker)
        if idx != -1:
            cut = min(cut, idx)
    prefix = text[:cut].strip()
    if prefix:
        return prefix
    return "(model returned tool syntax as text — file may not have been written)"


def extract_text_tool_calls(content: str) -> list[dict[str, Any]]:
    """Recover write_file/read_file/etc. when the model prints Qwen-style XML."""
    if not content or "<function=" not in content.lower():
        return []

    param_re = re.compile(
        r"<parameter=(\w+)>\s*(.*?)\s*</parameter>",
        re.DOTALL | re.IGNORECASE,
    )
    calls: list[dict[str, Any]] = []

    for match in re.finditer(
        r"<function=(\w+)>(.*?)(?=</function>|<function=|$)",
        content,
        re.DOTALL | re.IGNORECASE,
    ):
        name = match.group(1)
        body = match.group(2)
        args: dict[str, str] = {}
        for param in param_re.finditer(body):
            args[param.group(1)] = param.group(2).strip()
        if not name or not args:
            continue
        calls.append(
            {
                "id": f"text_{len(calls)}",
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)},
            }
        )
    return calls
