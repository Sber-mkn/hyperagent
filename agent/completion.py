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
    fix: str = ""
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
        summaries: list[str] | None = None,
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
                        "JSON only with completed (boolean), reason (string) and "
                        "fix (string). Judge only the given Task and its proposed "
                        "final answer. The recorded trajectory may contain earlier, "
                        "unrelated user tasks (already answered, successfully or "
                        "not) — treat those strictly as historical context, never "
                        "as open requirements of the current task. Do not fail the "
                        "current answer because an earlier, different task was "
                        "left unverified or incomplete. Use actual tool results as "
                        "evidence, not the assistant's claims or intentions. "
                        "Promises, plans, future actions, missing requested "
                        "artifacts, failed tools, and unverified results mean "
                        "completed=false. Explanations and ordinary conversation "
                        "can be complete without tools when the user did not "
                        "request an action or verification. Treat facts stated by "
                        "the user in the recorded conversation or memory summaries "
                        "as valid evidence for recall questions. Preserve the "
                        "user's meaning for labels such as code, name, "
                        "or value; do not reinterpret them as requests for "
                        "executable source code or additional artifacts. If "
                        "uncertain, return false. When completed=false, fix must be "
                        "one concrete, actionable instruction telling the assistant "
                        "exactly what to do next: which specific unverified claim "
                        "to drop or qualify as uncertain, which tool call would "
                        "supply the missing evidence, or that the answer should "
                        "state the confirmed facts plainly and flag the rest as "
                        "unconfirmed instead of retrying the same search. Do not "
                        "write a generic instruction like 'verify your claims' — "
                        "name the exact claim or step. When completed=true, fix "
                        "must be an empty string."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Task:\n{task}\n\n"
                        "Earlier memory summaries:\n"
                        f"{json.dumps(summaries or [], ensure_ascii=False)}\n\n"
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
            fix = " ".join(str(data.get("fix") or "").split())
            if not reason:
                raise ValueError("Completion review did not provide a reason")
            return CompletionReview(completed=completed, reason=reason, fix=fix)
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
