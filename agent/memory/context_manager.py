from __future__ import annotations

from agent.config import AGENT_WORKDIR
from agent.llminterface.client.llm_chat import LLMChat, LLMMessage
from agent.memory.store import MemoryStore, Turn


def _system_guidelines() -> str:
    workdir = AGENT_WORKDIR.as_posix()
    return (
        "Guidelines:\n"
        f"- Save user deliverables under {workdir}/.\n"
        "- For any coding task: call write_file with full file content, then verify with run_python.\n"
        "- Do not paste full file contents only in chat — use write_file.\n"
        "- Use installed libraries: pandas, numpy, matplotlib, seaborn, openpyxl, requests, "
        "scikit-learn, nbformat, pygame.\n"
        "- Save PDFs with matplotlib (plt.savefig). Do not use fpdf.\n"
        "- Fetch real data from public APIs when needed.\n"
        "- When finished, answer in plain text without tool calls."
    )


class ContextManager:
    """Build the prompt from layers L0–L3 before each model call."""

    def __init__(self, store: MemoryStore):
        self.store = store

    def build_working_chat(self) -> LLMChat:
        """Return system + user task + compressed history + recent tail for the ReAct loop."""
        parts: list[str] = []

        l0 = self.store.read_identity()
        if l0:
            parts.append(l0)

        parts.append(_system_guidelines())

        if self.store.summaries:
            parts.append("## Compressed earlier dialogue (L3)\n" + "\n".join(self.store.summaries))

        system_content = "\n\n".join(parts)
        messages: list[LLMMessage | dict] = [{"role": "system", "content": system_content}]

        if self.store.current_task:
            messages.append({"role": "user", "content": self.store.current_task})

        for turn in self.store.tail:
            if turn.role == "assistant":
                if turn.tool_calls:
                    messages.append(
                        LLMMessage(
                            role="assistant",
                            content=turn.content or "",
                            tool_calls=turn.tool_calls,
                        )
                    )
                else:
                    messages.append({"role": "assistant", "content": turn.content or ""})
            elif turn.role == "user":
                messages.append({"role": "user", "content": turn.content})
            elif turn.role == "tool":
                messages.append(
                    LLMMessage.tool_result(
                        turn.tool_name or "tool",
                        turn.content,
                        tool_call_id=turn.tool_call_id,
                    )
                )

        return LLMChat(messages)
