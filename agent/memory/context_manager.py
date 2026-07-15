"""Build model context from the four memory layers."""

from __future__ import annotations

from datetime import datetime, timezone

from agent.config import AGENT_WORKDIR, CONSTITUTION_DIR
from agent.llminterface.client.llm_chat import LLMChat, LLMMessage
from agent.memory.store import MemoryStore, Turn


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
        messages.extend(self._to_message(turn) for turn in self.store.tail)
        return LLMChat(messages)

    @staticmethod
    def _to_message(turn: Turn) -> LLMMessage | dict:
        if turn.role == "assistant" and turn.tool_calls:
            return LLMMessage(
                done=True,
                role="assistant",
                thinking="",
                content=turn.content,
                tool_calls=turn.tool_calls,
            )
        if turn.role == "tool":
            return LLMMessage.tool_result(
                turn.tool_name or "tool",
                turn.content,
                turn.tool_call_id,
            )
        return {"role": turn.role, "content": turn.content}

    @staticmethod
    def _constitution() -> str:
        path = CONSTITUTION_DIR / "identity.md"
        if not path.is_file():
            raise FileNotFoundError(f"Agent constitution not found: {path}")
        return path.read_text(encoding="utf-8").strip()

    @staticmethod
    def _runtime_guidance() -> str:
        current_date = datetime.now(timezone.utc).date().isoformat()
        return (
            f"The authoritative current runtime date is {current_date} UTC. "
            "Use this date even if conversation history, memory summaries, or "
            "earlier assistant answers claim a different current date. "
            "For time-sensitive questions about today, schedules, news, prices, "
            "or live events, verify the answer using available web tools instead "
            "of relying on training knowledge. "
            f"Save user deliverables under {AGENT_WORKDIR.as_posix()}/. "
            "Use tools to complete and verify the task. "
            "When a task may match a learned reusable procedure, call skills_list "
            "and then load the relevant instructions with skill_view before acting. "
            "Skill learning runs automatically after verified finalization. Never "
            "create or modify Python files under agent/skills manually. "
            "When finished, answer plainly without another tool call."
        )
