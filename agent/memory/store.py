"""In-memory L1-L3 view built from supervisor-owned conversation history."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Literal

from agent.config import L2_TOKEN_BUDGET


Role = Literal["user", "assistant", "tool"]


def estimate_tokens(text: str) -> int:
    """Return a cheap, deterministic token estimate."""
    return max(1, len(text) // 4) if text else 0


@dataclass
class Turn:
    role: Role
    content: str = ""
    thinking: str = ""
    message_id: int | None = None
    tool_name: str | None = None
    tool_call_id: str | None = None
    tool_calls: list[dict[str, Any]] | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.thinking:
            data["thinking"] = self.thinking
        if self.tool_name:
            data["tool_name"] = self.tool_name
        if self.tool_call_id:
            data["tool_call_id"] = self.tool_call_id
        if self.tool_calls:
            data["tool_calls"] = self.tool_calls
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Turn":
        return cls(
            role=data["role"],
            content=data.get("content", ""),
            thinking=data.get("thinking", ""),
            message_id=_message_id(data.get("id") or data.get("message_id")),
            tool_name=data.get("tool_name"),
            tool_call_id=data.get("tool_call_id"),
            tool_calls=data.get("tool_calls"),
        )

    @classmethod
    def from_llm_message(cls, message: dict[str, Any]) -> "Turn | None":
        role = message.get("role")
        if role not in {"user", "assistant", "tool"}:
            return None

        content = str(message.get("content") or "")
        tool_name = message.get("name") or message.get("tool_name")
        if role == "tool" and not tool_name and content.startswith("["):
            closing = content.find("]")
            if closing > 1:
                tool_name = content[1:closing]

        return cls(
            role=role,
            content=content,
            thinking=str(message.get("thinking") or ""),
            message_id=_message_id(message.get("id")),
            tool_name=tool_name,
            tool_call_id=message.get("tool_call_id"),
            tool_calls=message.get("tool_calls"),
        )

    def context_text(self) -> str:
        calls = json.dumps(self.tool_calls, ensure_ascii=False) if self.tool_calls else ""
        return " ".join(part for part in (self.role, self.content, calls) if part)


@dataclass
class MemoryStore:
    l2_token_budget: int = L2_TOKEN_BUDGET
    tail: list[Turn] = field(default_factory=list)
    summaries: list[str] = field(default_factory=list)
    last_compressed_message_id: int | None = None
    current_task: str = ""

    @classmethod
    def from_llm_chat(
        cls,
        messages: list[dict[str, Any]] | None,
        l2_token_budget: int = L2_TOKEN_BUDGET,
        l3_memory: dict[str, Any] | None = None,
    ) -> "MemoryStore":
        history = list(messages or [])
        if history and all(message.get("dt") for message in history):
            history.sort(key=lambda message: str(message["dt"]))

        summary = str((l3_memory or {}).get("summary") or "").strip()
        watermark = _message_id((l3_memory or {}).get("last_message_id"))
        if summary and watermark is not None:
            history = [
                message
                for message in history
                if (message_id := _message_id(message.get("id"))) is None
                or message_id > watermark
            ]

        turns = [Turn.from_llm_message(message) for message in history]
        return cls(
            l2_token_budget=l2_token_budget,
            tail=[turn for turn in turns if turn is not None],
            summaries=[summary] if summary else [],
            last_compressed_message_id=watermark if summary else None,
        )

    def set_task(self, task: str, resume: bool = False) -> bool:
        self.current_task = task.strip()
        if resume:
            latest_user = next(
                (turn for turn in reversed(self.tail) if turn.role == "user"),
                None,
            )
            if latest_user and latest_user.content.strip() == self.current_task:
                return False
        self.append(Turn(role="user", content=self.current_task))
        return True

    def append(self, turn: Turn) -> None:
        self.tail.append(turn)

    def tail_tokens(self) -> int:
        return sum(estimate_tokens(turn.context_text()) for turn in self.tail)

    def current_exchange(self) -> list[Turn]:
        """Return the latest user task and all turns produced for it."""
        return list(self.tail[self._current_turn_start():])

    def _current_turn_start(self) -> int:
        """Index of the latest user message; turns from here stay uncompressed."""
        for index in range(len(self.tail) - 1, -1, -1):
            if self.tail[index].role == "user":
                return index
        return len(self.tail)

    def maybe_compress(
        self,
        summarize: Callable[[list[Turn]], str],
    ) -> dict[str, Any] | None:
        changed = False
        while self.tail and self.tail_tokens() > self.l2_token_budget:
            segment = self._compression_segment()
            if segment is None:
                break
            start, end = segment

            summary = summarize(self.tail[start:end]).strip()
            if not summary:
                break

            message_ids = [
                turn.message_id
                for turn in self.tail[start:end]
                if turn.message_id is not None
            ]
            if message_ids:
                self.last_compressed_message_id = max(message_ids)
            self.summaries.append(summary)
            del self.tail[start:end]
            changed = True

        if not changed or self.last_compressed_message_id is None:
            return None
        return {
            "summary": "\n\n".join(self.summaries),
            "last_message_id": self.last_compressed_message_id,
        }

    def _compression_segment(self) -> tuple[int, int] | None:
        """Choose an old complete exchange without orphaning tool messages."""
        protected_from = self._current_turn_start()
        if protected_from <= 0:
            return None

        compressible = self.tail[:protected_from]

        for index in range(1, len(compressible)):
            if compressible[index].role == "user":
                return 0, index

        return 0, len(compressible)


def _message_id(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
