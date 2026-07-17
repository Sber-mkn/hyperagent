import json
from datetime import datetime

import requests

from agent.llminterface.client.llm_chat import LLMMessage, LLMChat, LLMTokens, LLMDuration
from agent.llminterface.client.llm_client import LLMClient

from typing import Optional, List, Dict, Any, Generator, Callable

class OllamaClient(LLMClient):
    """Класс для работы с провайдером Ollama"""

    _url: str
    default_ollama_options: dict
    default_model_options: dict

    TOP_LEVEL_KEYS = {"model", "messages", "stream", "format", "keep_alive", "tools"}

    @classmethod
    def _split_params(cls, parameters: dict) -> tuple[dict, dict]:
        """Разибение общих параметров на параметры ollama и параметры модели"""

        ollama_options = {}
        model_options = {}

        for key, value in parameters.items():
            if key in cls.TOP_LEVEL_KEYS:
                ollama_options[key] = value
            else:
                model_options[key] = value
        return ollama_options, model_options

    def _create_temp_params(self, parameters: dict) -> tuple[dict, dict]:
        ollama_options, model_options = self._split_params(parameters)
        return {**self.default_ollama_options, **ollama_options}, {**self.default_model_options, **model_options}

    def _create_payload(self, parameters) -> Dict[str, Any]:
        temp_ollama_options, temp_model_options = self._create_temp_params(parameters)
        payload = {
            **temp_ollama_options,
            "options": temp_model_options
        }
        return payload

    def __init__(
            self,
            url: str,
            timeout: int = 600,
            **parameters
    ):
        self._url = url
        self.timeout = timeout
        self.default_ollama_options, self.default_model_options = self._split_params(parameters)


    @staticmethod
    def _ns_to_s(value: Optional[int]) -> Optional[float]:
        """Ollama отдаёт длительности в наносекундах — переводим в секунды,
        чтобы значения помещались в БД (см. duration_* колонки в llmchat)."""
        return value / 1e9 if value is not None else None

    def _parse_response(self, response: Dict[str, Any]) -> LLMMessage:
        message = response.get("message", {})

        return LLMMessage(
            done=response.get("done", True),
            done_reason=response.get("done_reason"),
            role=message.get("role", "assistant"),
            thinking=message.get("thinking", ""),
            content=message.get("content", ""),
            tool_calls=message.get("tool_calls"),
            provider="ollama",
            model=response.get("model", ""),
            tokens=LLMTokens(
                prompt=response.get("prompt_eval_count"),
                response=response.get("eval_count"),
            ),
            duration=LLMDuration(
                load=self._ns_to_s(response.get("load_duration")),
                prompt=self._ns_to_s(response.get("prompt_eval_duration")),
                response=self._ns_to_s(response.get("eval_duration")),
            ),
            dt=datetime.now(),
        )

    def send(
            self,
            chat: LLMChat,
            **kwargs: int | float | str | bool
    ) -> LLMChat:
        payload = self._create_payload(kwargs)
        payload["messages"] = chat.to_payload()
        payload["stream"] = False

        response = requests.post(self._url, json=payload, stream=False, timeout=self.timeout)
        response.raise_for_status()

        return chat + self._parse_response(response.json())

    def stream(
            self,
            chat: LLMChat,
            on_chunk_think: Optional[Callable[[str], None]]=None,
            on_chunk_content: Optional[Callable[[str], None]]=None,
            **kwargs: int | float | str | bool
    ) -> LLMChat:
        payload = self._create_payload(kwargs)
        payload["messages"] = chat.to_payload()
        payload["stream"] = True

        llm_message = LLMMessage(
            done=False,
            role="assistant",
            thinking="",
            content="",
            provider="ollama",
            model=payload.get("model", "")
        )

        response = requests.post(self._url, json=payload, stream=True, timeout=self.timeout)

        try:
            response.raise_for_status()

            with response:
                for line in response.iter_lines():
                    if not line:
                        continue

                    delta = self._parse_response(json.loads(line.decode("utf-8")))

                    llm_message.content += delta.content
                    llm_message.thinking += delta.thinking

                    if delta.tool_calls:
                        llm_message.tool_calls = (llm_message.tool_calls or []) + delta.tool_calls

                    if delta.done:
                        llm_message.done = True
                        llm_message.done_reason = delta.done_reason
                        llm_message.model = delta.model or llm_message.model
                        llm_message.tokens = delta.tokens
                        llm_message.duration = delta.duration
                        llm_message.dt = delta.dt

                    if on_chunk_think and delta.thinking:
                        on_chunk_think(delta.thinking)

                    if on_chunk_content and delta.content:
                        on_chunk_content(delta.content)
        finally:
            if not llm_message.done:
                llm_message.done=True
                llm_message.done_reason="cancelled"
                response.close()
        return chat + llm_message
