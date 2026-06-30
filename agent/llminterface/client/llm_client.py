from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, Callable

import json

import requests
import datetime

from agent.llminterface.client.llm_chat import LLMChat



class LLMClient(ABC):
    """Класс для работы с провайдерами LLM"""

    provider: str
    model: str

    tools: List[Dict[str, Any]]

    end_time: datetime.datetime

    timeout: int

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


