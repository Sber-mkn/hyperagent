"""Parse a JSON object out of an LLM response's message."""

from __future__ import annotations

import json
import re
from typing import Protocol


class _JsonBearingMessage(Protocol):
    content: str
    thinking: str


def parse_llm_json(message: _JsonBearingMessage) -> dict:
    """Extract and parse the JSON object an LLM was asked to return.

    A reasoning model can put its whole answer -- including the JSON itself --
    into "thinking" and leave "content" empty; fall back to thinking rather
    than failing on an empty string. Also tolerate the JSON trailing a
    reasoning trace, or wrapped in a markdown code fence, instead of being
    the entire response verbatim, by extracting the last top-level
    brace-balanced object in the text.
    """
    raw = (message.content or "").strip() or (message.thinking or "")
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text).strip()
    text = _last_top_level_object(text) or text
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("Response must be a JSON object")
    return data


def _last_top_level_object(text: str) -> str | None:
    """Return the last top-level {...} span in text, honoring nesting and
    string literals (so a brace inside a quoted value doesn't miscount)."""
    candidates: list[str] = []
    depth = 0
    start: int | None = None
    in_string = False
    escape = False
    for i, ch in enumerate(text):
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}" and depth > 0:
            depth -= 1
            if depth == 0 and start is not None:
                candidates.append(text[start:i + 1])
    return candidates[-1] if candidates else None
