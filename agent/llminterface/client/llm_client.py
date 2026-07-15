from abc import abstractmethod
from typing import List, Dict, Any, Optional, Callable

import datetime

from agent.llminterface.client.llm_chat import LLMChat, LLMMessage
from agent.llminterface.agent_chain.executable import Executable



class LLMClient(Executable):
    """Класс для работы с провайдерами LLM"""

    provider: str
    model: str

    tools: List[Dict[str, Any]]

    end_time: datetime.datetime

    timeout: int

    @abstractmethod
    def _parse_response(self, response: Dict[str, Any]) -> LLMMessage:
        """Разобрать сырой ответ провайдера в LLMMessage.
        Здесь и только здесь клиент знает формат своего API (поля токенов,
        длительностей, thinking/content и т.д.) — LLMMessage остаётся
        провайдер-агностичным."""
        ...

    @abstractmethod
    def send(
            self,
            chat: LLMChat,
            **kwargs: int | float | str | bool
    ) -> LLMChat:
        ...

    @abstractmethod
    def stream(
            self,
            chat: LLMChat,
            on_chunk_think: Optional[Callable[[str], None]],
            on_chunk_content: Optional[Callable[[str], None]],
            **kwargs: int | float | str | bool
    ) -> LLMChat:
        ...

    def run(self, *args, **kwargs):
        return self.send(*args, **kwargs)

