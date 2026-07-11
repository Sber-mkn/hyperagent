"""Persistent L1-L3 memory for one agent session."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal

from agent.config import DATA_DIR, L2_TOKEN_BUDGET


Role = Literal["user", "assistant", "tool"]
FORMAT_VERSION = 2


def estimate_tokens(text: str) -> int:
    """Return a cheap, deterministic token estimate."""
    return max(1, len(text) // 4) if text else 0


@dataclass
class Turn:
    role: Role
    content: str = ""
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

    def context_text(self) -> str:
        calls = json.dumps(self.tool_calls, ensure_ascii=False) if self.tool_calls else ""
        return " ".join(part for part in (self.role, self.content, calls) if part)


@dataclass
class MemoryStore:
    data_dir: Path
    l2_token_budget: int = L2_TOKEN_BUDGET
    tail: list[Turn] = field(default_factory=list)
    summaries: list[str] = field(default_factory=list)
    current_task: str = ""

    @property
    def log_path(self) -> Path:
        return self.data_dir / "logs" / "chat.jsonl"

    @property
    def blocks_path(self) -> Path:
        return self.data_dir / "memory" / "dialogue_blocks.json"

    @classmethod
    def reset(cls, data_dir: Path = DATA_DIR) -> None:
        if data_dir.exists():
            shutil.rmtree(data_dir)

    @classmethod
    def open(
        cls,
        data_dir: Path = DATA_DIR,
        l2_token_budget: int = L2_TOKEN_BUDGET,
    ) -> "MemoryStore":
        store = cls(Path(data_dir), l2_token_budget)
        store._ensure_layout()
        store._load()
        return store

    def _ensure_layout(self) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.blocks_path.parent.mkdir(parents=True, exist_ok=True)

    def _load(self) -> None:
        if not self.blocks_path.exists():
            return
        data = json.loads(self.blocks_path.read_text(encoding="utf-8"))
        self.summaries = list(data.get("summaries", []))
        if data.get("version") == FORMAT_VERSION:
            self.tail = [Turn.from_dict(item) for item in data.get("tail", [])]

    def _save(self) -> None:
        data = {
            "version": FORMAT_VERSION,
            "tail": [turn.to_dict() for turn in self.tail],
            "summaries": self.summaries,
        }
        self.blocks_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def set_task(self, task: str) -> None:
        self.current_task = task.strip()
        self.append(Turn(role="user", content=self.current_task))

    def append(self, turn: Turn) -> None:
        self.tail.append(turn)
        self._append_log(turn)
        self._save()

    def tail_tokens(self) -> int:
        return sum(estimate_tokens(turn.context_text()) for turn in self.tail)

    def maybe_compress(self, summarize: Callable[[list[Turn]], str]) -> bool:
        changed = False
        while self.tail and self.tail_tokens() > self.l2_token_budget:
            segment = self._compression_segment()
            if segment is None:
                break
            start, end = segment

            summary = summarize(self.tail[start:end]).strip()
            if not summary:
                break

            self.summaries.append(summary)
            del self.tail[start:end]
            changed = True

        if changed:
            self._save()
        return changed

    def _compression_segment(self) -> tuple[int, int] | None:
        """Choose an old complete exchange without orphaning tool messages."""
        for index in range(1, len(self.tail)):
            if self.tail[index].role == "user":
                return 0, index

        start = 1 if self.tail and self.tail[0].role == "user" else 0
        if start >= len(self.tail):
            return None

        end = start + 1
        while end < len(self.tail) and self.tail[end].role == "tool":
            end += 1
        return start, end

    def _append_log(self, turn: Turn) -> None:
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            **turn.to_dict(),
        }
        with self.log_path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(record, ensure_ascii=False) + "\n")
