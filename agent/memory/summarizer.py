"""Compress older L2 turns into L3 session summaries."""

from __future__ import annotations

import json
from typing import Any

from agent.llminterface.client.llm_chat import LLMChat
from agent.llminterface.client.llm_client import LLMClient
from agent.memory.store import Turn


class Summarizer:
    def __init__(self, client: LLMClient, model: str, options: dict[str, Any] | None = None):
        self.client = client
        self.model = model
        self.options = options or {}

    def summarize(self, turns: list[Turn]) -> str:
        if not turns:
            return ""

        history = "\n".join(
            json.dumps(turn.to_dict(), ensure_ascii=False) for turn in turns
        )
        chat = LLMChat(
            [
                {
                    "role": "system",
                    "content": (
                        "Compress agent history. Preserve decisions, paths, errors, "
                        "tool results, and unfinished work. Do not invent facts."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Summarize these turns in 2-4 concise bullets:\n{history}",
                },
            ]
        )
        result = self.client.send(chat, model=self.model, temperature=0, **self.options)
        return (result[-1].content or "").strip()
