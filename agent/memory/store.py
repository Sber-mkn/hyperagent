from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal

from agent.config import CHAT_LOG_PATH, DIALOGUE_BLOCKS_PATH, IDENTITY_PATH, L2_TOKEN_BUDGET


Role = Literal["user", "assistant", "tool", "system"]


def estimate_tokens(text: str) -> int:
    """Rough token estimate (~4 chars per token) — good enough for L2 budgeting."""
    if not text:
        return 0
    return max(1, len(text) // 4)


@dataclass
class Turn:
    role: Role
    content: str
    tool_name: str | None = None
    tool_call_id: str | None = None
    tool_calls: list[dict[str, Any]] | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"role": self.role, "content": self.content}
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
            tool_name=data.get("tool_name"),
            tool_call_id=data.get("tool_call_id"),
            tool_calls=data.get("tool_calls"),
        )

    def label(self) -> str:
        if self.role == "tool" and self.tool_name:
            return f"[tool:{self.tool_name}] {self.content}"
        prefix = self.role.upper()
        return f"{prefix}: {self.content}"


MAX_TURN_CHARS = 16000


@dataclass
class MemoryStore:
    """plain-file persistence for V3."""

    data_dir: Path
    l2_token_budget: int = L2_TOKEN_BUDGET
    tail: list[Turn] = field(default_factory=list)
    summaries: list[str] = field(default_factory=list)
    current_task: str = ""

    @property
    def identity_path(self) -> Path:
        return self.data_dir / "memory" / "identity.md"

    @property
    def chat_log_path(self) -> Path:
        return self.data_dir / "logs" / "chat.jsonl"

    @property
    def dialogue_blocks_path(self) -> Path:
        return self.data_dir / "memory" / "dialogue_blocks.json"

    @classmethod
    def reset(cls, data_dir: Path) -> None:
        """Remove persisted session data (keeps layout fresh for the next run)."""
        import shutil

        if data_dir.exists():
            shutil.rmtree(data_dir)

    @classmethod
    def open(cls, data_dir: Path, l2_token_budget: int = L2_TOKEN_BUDGET) -> "MemoryStore":
        store = cls(data_dir=data_dir, l2_token_budget=l2_token_budget)
        store._ensure_layout()
        store._load_blocks()
        return store

    def _ensure_layout(self) -> None:
        (self.data_dir / "logs").mkdir(parents=True, exist_ok=True)
        (self.data_dir / "memory").mkdir(parents=True, exist_ok=True)
        if not self.identity_path.exists():
            self.identity_path.write_text(DEFAULT_IDENTITY, encoding="utf-8")

    def _load_blocks(self) -> None:
        if not self.dialogue_blocks_path.exists():
            return
        raw = json.loads(self.dialogue_blocks_path.read_text(encoding="utf-8"))
        self.tail = [Turn.from_dict(t) for t in raw.get("tail", [])]
        self.summaries = list(raw.get("summaries", []))

    def _save_blocks(self) -> None:
        payload = {
            "tail": [t.to_dict() for t in self.tail],
            "summaries": self.summaries,
        }
        self.dialogue_blocks_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def read_identity(self) -> str:
        return self.identity_path.read_text(encoding="utf-8").strip()

    def set_task(self, task: str) -> None:
        self.current_task = task.strip()
        self._append_log("user", task)

    def append_turn(self, turn: Turn) -> None:
        content = turn.content
        if len(content) > MAX_TURN_CHARS:
            content = content[:MAX_TURN_CHARS] + "\n...[truncated]"
            turn = Turn(
                role=turn.role,
                content=content,
                tool_name=turn.tool_name,
                tool_call_id=turn.tool_call_id,
                tool_calls=turn.tool_calls,
            )
        self.tail.append(turn)
        self._append_log(turn.role, turn.content, turn.tool_name)
        self._save_blocks()

    def tail_token_count(self) -> int:
        return sum(estimate_tokens(t.label()) for t in self.tail)

    def pop_oldest_tail(self, count: int = 1) -> list[Turn]:
        moved = self.tail[:count]
        self.tail = self.tail[count:]
        self._save_blocks()
        return moved

    def add_summary(self, text: str) -> None:
        cleaned = text.strip()
        if cleaned:
            self.summaries.append(cleaned)
            self._save_blocks()

    def maybe_compress(self, summarizer: Callable[[list[Turn]], str]) -> bool:
        """Move oldest tail turns into L3 when L2 exceeds the token budget."""
        changed = False
        while self.tail and self.tail_token_count() > self.l2_token_budget:
            batch: list[Turn] = []
            while self.tail and self.tail_token_count() > self.l2_token_budget:
                batch.append(self.tail.pop(0))
            if not batch:
                break
            summary = summarizer(batch)
            self.add_summary(summary)
            changed = True
        return changed

    def _append_log(self, role: str, content: str, tool_name: str | None = None) -> None:
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "role": role,
            "content": content,
        }
        if tool_name:
            record["tool_name"] = tool_name
        with self.chat_log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")


DEFAULT_IDENTITY = """# Agent identity (L0)

You are a capable coding agent. Reply in English unless the user writes in another language.
Use the available tools to finish tasks completely: write files, run and verify.
When the task is done, reply with a short plain-text summary and stop calling tools.
You are the only model — plan the work and write code yourself via write_file.
"""
