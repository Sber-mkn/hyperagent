from abc import ABC, abstractmethod
from typing import Callable, Optional

from agent.llminterface.agent_chain.executable import Executable
from agent.llminterface.client.llm_chat import LLMChat


class LLMClient(Executable):
    """Abstract client for LLM providers (Ollama, OpenRouter, …)."""

    provider: str
    timeout: int

    @abstractmethod
    def send(self, chat: LLMChat, **kwargs) -> LLMChat:
        ...

    @abstractmethod
    def stream(
        self,
        chat: LLMChat,
        on_chunk_think: Optional[Callable[[str], None]],
        on_chunk_content: Optional[Callable[[str], None]],
        **kwargs,
    ) -> LLMChat:
        ...

    def run(self, *args, **kwargs):
        return self.send(*args, **kwargs)
