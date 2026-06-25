import requests
import json
from typing import List, Dict, Any, Optional, Iterator
import time
import re

from abc import ABC, abstractmethod
from agent.llminterface.llm_response import LLMStreamingResponse, LLMResponse, Usage, Timing

import pprint


class LLMClient(ABC):
    """Класс для работы с разными провайдерами LLM моделей"""
    @abstractmethod
    def chat(
            self,
            messages: List[Dict[str, Any]],
            tools: Optional[List[Dict[str, Any]]] = None,
            timeout: int = 300,
            **kwargs: int | float | str | bool
    ) -> LLMResponse:
        ...

    @abstractmethod
    def stream(
            self,
            messages: List[Dict[str, Any]],
            tools: Optional[List[Dict[str, Any]]] = None,
            timeout: int = 300,
            **kwargs: int | float | str | bool
    ) -> LLMStreamingResponse:
        ...

    @property
    @abstractmethod
    def time_alive(self) -> float | None:
        ...

    @property
    @abstractmethod
    def keep_alive(self):
        ...




