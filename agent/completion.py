"""Verify a proposed final answer against the completed task trajectory."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from agent.llminterface.client.llm_chat import LLMChat
from agent.llminterface.client.llm_client import LLMClient

if TYPE_CHECKING:
    from agent.memory.store import Turn


@dataclass(frozen=True)
class CompletionReview:
    completed: bool
    reason: str
    available: bool = True


class CompletionChecker:
    def __init__(self, client: LLMClient, model: str, options: dict[str, Any] | None = None):
        self.client = client
        self.model = model
        self.options = options or {}

    def check(
        self,
        task: str,
        turns: list[Turn],
        candidate_answer: str,
    ) -> CompletionReview:
        trajectory = json.dumps(
            [turn.to_dict() for turn in turns],
            ensure_ascii=False,
        )
        chat = LLMChat(
            [
                {
                    "role": "system",
                    "content": (
                        "Verify whether an agent task is actually complete. Return "
                        "JSON only with completed (boolean) and reason (string). "
                        "Use actual tool results as evidence, not the assistant's "
                        "claims or intentions. Promises, plans, future actions, "
                        "missing requested artifacts, failed tools, and unverified "
                        "results mean completed=false. Explanations and ordinary "
                        "conversation can be complete without tools when the user "
                        "did not request an action or verification. If uncertain, "
                        "return false."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Task:\n{task}\n\n"
                        f"Recorded trajectory:\n{trajectory}\n\n"
                        f"Proposed final answer:\n{candidate_answer}"
                    ),
                },
            ]
        )

        try:
            response = self.client.send(chat, model=self.model, temperature=0, **self.options)
            data = _parse_json(response[-1].content or "")
            completed = data.get("completed") is True
            reason = " ".join(str(data.get("reason") or "").split())
            if not reason:
                raise ValueError("Completion review did not provide a reason")
            return CompletionReview(completed=completed, reason=reason)
        except Exception as error:
            return CompletionReview(
                completed=False,
                reason=f"Completion verification failed: {error}",
                available=False,
            )


def _parse_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("Completion review must be a JSON object")
    return data
