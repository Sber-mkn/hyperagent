import json
import os
from collections.abc import Callable
from datetime import datetime
from typing import Any

import requests

from agent.llminterface.client.llm_chat import LLMChat, LLMMessage, LLMTokens
from agent.llminterface.client.llm_client import LLMClient


class OpenaiClient(LLMClient):
    """Клиент для OpenAI-совместимого chat-completions API.

    Подходит для самого OpenAI и для любого провайдера/роутера, который проксирует тот же протокол (OpenRouter,
    Together, Groq, vLLM, LM Studio и т.д.)"""

    _base_url: str
    _api_key: str | None
    default_parameters: dict

    def __init__(
        self,
        base_url: str = "https://api.openai.com/v1",
        api_key: str | None = None,
        timeout: int = 600,
        **parameters: int | float | str | bool,
    ):
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self.timeout = timeout
        self.default_parameters = parameters

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    def _create_payload(self, parameters: dict) -> dict[str, Any]:
        return {**self.default_parameters, **parameters}

    def _parse_response(self, response: dict[str, Any]) -> LLMMessage:
        choice = (response.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        usage = response.get("usage") or {}

        return LLMMessage(
            done=True,
            done_reason=choice.get("finish_reason"),
            role=message.get("role", "assistant"),
            thinking=message.get("reasoning_content") or message.get("reasoning") or "",
            content=message.get("content") or "",
            tool_calls=message.get("tool_calls"),
            provider="openai",
            model=response.get("model", ""),
            tokens=LLMTokens(
                prompt=usage.get("prompt_tokens"),
                response=usage.get("completion_tokens"),
            ),
            duration=None,  # недоступно в openai api
            dt=datetime.now(),
        )

    def send(
        self,
        chat: LLMChat,
        **kwargs: int | float | str | bool,
    ) -> LLMChat:
        payload = self._create_payload(kwargs)
        payload["messages"] = chat.to_payload()
        payload["stream"] = False

        response = requests.post(
            f"{self._base_url}/chat/completions",
            json=payload,
            headers=self._headers(),
            timeout=self.timeout,
        )
        response.raise_for_status()

        return chat + self._parse_response(response.json())

    def stream(
        self,
        chat: LLMChat,
        on_chunk_think: Callable[[str], None] | None = None,
        on_chunk_content: Callable[[str], None] | None = None,
        **kwargs: int | float | str | bool,
    ) -> LLMChat:
        payload = self._create_payload(kwargs)
        payload["messages"] = chat.to_payload()
        payload["stream"] = True
        payload.setdefault("stream_options", {"include_usage": True})

        content_parts: list[str] = []
        thinking_parts: list[str] = []
        tool_calls_acc: dict[int, dict[str, Any]] = {}
        finish_reason: str | None = None
        model_name = ""
        usage: dict[str, Any] = {}

        response = requests.post(
            f"{self._base_url}/chat/completions",
            json=payload,
            headers=self._headers(),
            stream=True,
            timeout=self.timeout,
        )

        done = False
        try:
            response.raise_for_status()

            with response:
                for line in response.iter_lines():
                    if not line:
                        continue
                    raw = line.decode("utf-8")
                    if not raw.startswith("data:"):
                        continue
                    raw = raw[len("data:") :].strip()
                    if raw == "[DONE]":
                        break

                    chunk = json.loads(raw)
                    model_name = chunk.get("model") or model_name
                    if chunk.get("usage"):
                        usage = chunk["usage"]

                    choices = chunk.get("choices") or []
                    if not choices:
                        continue

                    choice = choices[0]
                    delta = choice.get("delta") or {}
                    finish_reason = choice.get("finish_reason") or finish_reason

                    _content = delta.get("content") or ""
                    _thinking = delta.get("reasoning_content") or delta.get("reasoning") or ""

                    if _content:
                        content_parts.append(_content)
                    if _thinking:
                        thinking_parts.append(_thinking)

                    for tc in delta.get("tool_calls") or []:
                        idx = tc.get("index", 0)
                        acc = tool_calls_acc.setdefault(
                            idx,
                            {
                                "id": "",
                                "type": "function",
                                "function": {"name": "", "arguments": ""},
                            },
                        )
                        if tc.get("id"):
                            acc["id"] = tc["id"]
                        if tc.get("type"):
                            acc["type"] = tc["type"]
                        fn = tc.get("function") or {}
                        if fn.get("name"):
                            acc["function"]["name"] += fn["name"]
                        if fn.get("arguments"):
                            acc["function"]["arguments"] += fn["arguments"]

                    if on_chunk_think and _thinking:
                        on_chunk_think(_thinking)
                    if on_chunk_content and _content:
                        on_chunk_content(_content)
            done = True
        finally:
            if not done:
                finish_reason = finish_reason or "cancelled"
                response.close()

        assembled = {
            "model": model_name,
            "usage": usage,
            "choices": [
                {
                    "finish_reason": finish_reason,
                    "message": {
                        "role": "assistant",
                        "content": "".join(content_parts),
                        "reasoning_content": "".join(thinking_parts),
                        "tool_calls": [tool_calls_acc[i] for i in sorted(tool_calls_acc)] or None,
                    },
                }
            ],
        }
        return chat + self._parse_response(assembled)
