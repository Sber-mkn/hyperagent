from __future__ import annotations

from agent.llminterface.client.llm_chat import LLMChat
from agent.llminterface.client.llm_client import LLMClient
from agent.memory.store import Turn


class Summarizer:
    """Compress evicted L2 turns into L3 episodic summaries."""

    PROMPT = (
        "Summarize the following agent dialogue turns into 2-4 concise bullet points. "
        "Keep facts, decisions, file paths, errors, and fixes. Do not invent details.\n\n"
        "{turns}"
    )

    def __init__(self, client: LLMClient, model: str, temperature: float = 0.0):
        self.client = client
        self.model = model
        self.temperature = temperature

    def summarize(self, turns: list[Turn]) -> str:
        if not turns:
            return ""
        body = "\n".join(t.label() for t in turns)
        chat = LLMChat(
            [
                {
                    "role": "system",
                    "content": "You compress agent logs into short episodic summaries.",
                },
                {"role": "user", "content": self.PROMPT.format(turns=body)},
            ]
        )
        result = self.client.send(chat, model=self.model, temperature=self.temperature)
        return (result[-1].content or "").strip()
