"""Build model context from the four memory layers."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from agent.config import AGENT_WORKDIR, CONSTITUTION_DIR
from agent.llminterface.client.llm_chat import LLMChat, LLMMessage
from agent.memory.store import MemoryStore, Turn
from agent.tools.registry import truncate_middle

KEEP_FULL_TOOL_CALLS = 2
MAX_ARGUMENTS_CHARS = 600


class ContextManager:
    def __init__(self, store: MemoryStore, recovery_notice: str = ""):
        self.store = store
        self.recovery_notice = recovery_notice.strip()

    def build_chat(self) -> LLMChat:
        system_parts = [self._constitution(), self._runtime_guidance()]
        if self.recovery_notice:
            system_parts.append(self.recovery_notice)
        if self.store.summaries:
            summaries = "\n\n".join(self.store.summaries)
            system_parts.append(f"Earlier session summaries (L3):\n{summaries}")
        messages: list[LLMMessage | dict] = [
            {"role": "system", "content": "\n\n".join(system_parts)}
        ]
        messages.extend(self._build_turn_messages(self.store.tail))
        return LLMChat(messages)

    @staticmethod
    def _build_turn_messages(tail: list[Turn]) -> list[LLMMessage | dict]:
        total_calls: dict[str, int] = {}
        for turn in tail:
            for call in turn.tool_calls or []:
                name = (call.get("function") or {}).get("name")
                if name:
                    total_calls[name] = total_calls.get(name, 0) + 1

        seen_calls: dict[str, int] = {}

        def keep_full(name: str | None) -> bool:
            if not name:
                return True
            seen_calls[name] = seen_calls.get(name, 0) + 1
            remaining_after = total_calls.get(name, 0) - seen_calls[name]
            return remaining_after < KEEP_FULL_TOOL_CALLS

        messages: list[LLMMessage | dict] = []
        for turn in tail:
            if turn.role == "assistant" and turn.tool_calls:
                tool_calls = [
                    call
                    if keep_full((call.get("function") or {}).get("name"))
                    else _compact_call(call)
                    for call in turn.tool_calls
                ]
                messages.append(
                    LLMMessage(
                        done=True,
                        role="assistant",
                        thinking="",
                        content=turn.content,
                        tool_calls=tool_calls,
                    )
                )
            elif turn.role == "tool":
                messages.append(
                    LLMMessage.tool_result(
                        turn.tool_name or "tool", turn.content, turn.tool_call_id
                    )
                )
            else:
                messages.append({"role": turn.role, "content": turn.content})
        return messages

    @staticmethod
    def _constitution() -> str:
        path = CONSTITUTION_DIR / "identity.md"
        if not path.is_file():
            raise FileNotFoundError(f"Agent constitution not found: {path}")
        return path.read_text(encoding="utf-8").strip()

    @staticmethod
    def _runtime_guidance() -> str:
        current_date = datetime.now(UTC).date().isoformat()
        return (
            f"The authoritative current runtime date is {current_date} UTC. "
            "Use this date even if conversation history, memory summaries, or "
            "earlier assistant answers claim a different current date. "
            "For time-sensitive questions about today, schedules, news, prices, "
            "or live events, verify the answer using available web tools instead "
            "of relying on training knowledge. "
            f"Save user deliverables under {AGENT_WORKDIR.as_posix()}/ unless the "
            "task concerns the user's own computer — that machine is reached only "
            "through the client-side tools, so do the work there instead. "
            "Use tools to complete and verify the task. "
            "When a task may match a learned reusable procedure, call skills_list "
            "and then load the relevant instructions with skill_view before acting. "
            "Skill learning runs automatically after verified finalization. Never "
            "create or modify Python files under agent/skills manually. "
            "When finished, answer plainly without another tool call."
        )


def _compact_call(call: dict[str, Any]) -> dict[str, Any]:
    function = call.get("function") or {}
    arguments = function.get("arguments")
    if not isinstance(arguments, str) or len(arguments) <= MAX_ARGUMENTS_CHARS:
        return call

    compacted = dict(call)
    compacted["function"] = {
        **function,
        "arguments": truncate_middle(arguments, MAX_ARGUMENTS_CHARS)
        + " [earlier attempt in this task, truncated for context]",
    }
    return compacted
