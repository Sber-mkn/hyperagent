import json

import requests
from bottle import response

from agent.llminterface.client.llm_chat import LLMMessage, LLMChat, LLMTokens, LLMDuration
from agent.llminterface.client.llm_client import LLMClient

from typing import Optional, List, Dict, Any, Generator, Callable

class OllamaClient(LLMClient):
    """Класс для работы с провайдером Ollama"""

    _url: str
    default_ollama_options: dict
    default_model_options: dict

    TOP_LEVEL_KEYS = {"model", "messages", "stream", "format", "keep_alive"}

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

        return chat + LLMMessage.from_response(response.json(), "ollama")

    def stream(
            self,
            chat: LLMChat,
            on_chunk_think: Optional[Callable[[str], None]],
            on_chunk_content: Optional[Callable[[str], None]],
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
        chat.append(llm_message)

        response = requests.post(self._url, json=payload, stream=True, timeout=self.timeout)

        try:
            response.raise_for_status()

            with response:
                for line in response.iter_lines():
                    if not line:
                        continue

                    chunk = json.loads(line.decode("utf-8"))
                    message = chunk.get("message", {})

                    _content = message.get("content", "")
                    _thinking = message.get("thinking", "")
                    llm_message.content += _content
                    llm_message.thinking += _thinking

                    if chunk.get("done"):
                        llm_message.done = True
                        llm_message.done_reason = chunk.get("done_reason"),
                        llm_message.tokens = LLMTokens(
                            prompt=chunk.get("prompt_eval_count"),
                            response=chunk.get("eval_count"),
                        )
                        llm_message.duration = LLMDuration(
                            load=chunk.get("load_duration"),
                            prompt=chunk.get("prompt_eval_duration"),
                            response=chunk.get("eval_duration"),
                        )

                    if on_chunk_think and _thinking:
                        on_chunk_think(_thinking)

                    if on_chunk_content and _content:
                        on_chunk_content(_content)
        finally:
            if not llm_message.done:
                llm_message.done=True
                llm_message.done_reason="cancelled"
                response.close()
        return chat
