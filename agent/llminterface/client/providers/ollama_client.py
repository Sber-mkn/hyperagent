import json
from datetime import datetime
from typing import Any, Callable, Dict, Generator, Optional

import requests

from agent.llminterface.client.llm_chat import LLMChat, LLMDuration, LLMMessage, LLMTokens
from agent.llminterface.client.llm_client import LLMClient


class OllamaClient(LLMClient):
    """HTTP client for Ollama /api/chat."""

    provider = "ollama"
    TOP_LEVEL_KEYS = {"model", "messages", "stream", "format", "keep_alive", "tools"}

    @classmethod
    def _split_params(cls, parameters: dict) -> tuple[dict, dict]:
        ollama_options: dict = {}
        model_options: dict = {}
        for key, value in parameters.items():
            if key in cls.TOP_LEVEL_KEYS:
                ollama_options[key] = value
            else:
                model_options[key] = value
        return ollama_options, model_options

    def _create_temp_params(self, parameters: dict) -> tuple[dict, dict]:
        ollama_options, model_options = self._split_params(parameters)
        return {**self.default_ollama_options, **ollama_options}, {
            **self.default_model_options,
            **model_options,
        }

    def _create_payload(self, parameters) -> Dict[str, Any]:
        temp_ollama_options, temp_model_options = self._create_temp_params(parameters)
        return {**temp_ollama_options, "options": temp_model_options}

    def __init__(self, url: str, timeout: int = 600, **parameters):
        self._url = url
        self.timeout = timeout
        self.default_ollama_options, self.default_model_options = self._split_params(parameters)

    def send(self, chat: LLMChat, **kwargs) -> LLMChat:
        payload = self._create_payload(kwargs)
        payload["messages"] = chat.to_payload()
        payload["stream"] = False
        response = requests.post(self._url, json=payload, stream=False, timeout=self.timeout)
        response.raise_for_status()
        return chat + LLMMessage.from_ollama_response(response.json(), self.provider)

    def stream(
        self,
        chat: LLMChat,
        on_chunk_think: Optional[Callable[[str], None]],
        on_chunk_content: Optional[Callable[[str], None]],
        **kwargs,
    ) -> LLMChat:
        payload = self._create_payload(kwargs)
        payload["messages"] = chat.to_payload()
        payload["stream"] = True

        llm_message = LLMMessage(
            done=False,
            role="assistant",
            provider=self.provider,
            model=str(payload.get("model", "")),
        )

        response = requests.post(self._url, json=payload, stream=True, timeout=self.timeout)
        try:
            response.raise_for_status()
            with response:
                for line in response.iter_lines():
                    if not line:
                        continue
                    chunk = json.loads(line.decode("utf-8"))
                    message = chunk.get("message", {})
                    content = message.get("content", "")
                    thinking = message.get("thinking", "")
                    llm_message.content += content
                    llm_message.thinking += thinking
                    tool_calls = message.get("tool_calls")
                    if tool_calls:
                        llm_message.tool_calls = (llm_message.tool_calls or []) + tool_calls
                    if chunk.get("done"):
                        llm_message.done = True
                        llm_message.done_reason = chunk.get("done_reason")
                        llm_message.tokens = LLMTokens(
                            prompt=chunk.get("prompt_eval_count"),
                            response=chunk.get("eval_count"),
                        )
                        llm_message.duration = LLMDuration(
                            load=chunk.get("load_duration"),
                            prompt=chunk.get("prompt_eval_duration"),
                            response=chunk.get("eval_duration"),
                        )
                        llm_message.dt = datetime.now()
                    if on_chunk_think and thinking:
                        on_chunk_think(thinking)
                    if on_chunk_content and content:
                        on_chunk_content(content)
        finally:
            if not llm_message.done:
                llm_message.done = True
                llm_message.done_reason = "cancelled"
                response.close()
        return chat + llm_message
