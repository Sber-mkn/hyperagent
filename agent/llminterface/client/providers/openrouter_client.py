from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Callable, Dict, Optional

import requests

from agent.llminterface.client.llm_chat import LLMChat, LLMMessage
from agent.llminterface.client.llm_client import LLMClient

logger = logging.getLogger(__name__)

_RETRYABLE_STATUS = {429, 500, 502, 503, 504}
_MAX_RETRIES = int(os.getenv("OPENROUTER_MAX_RETRIES", "5"))


class OpenRouterClient(LLMClient):
    """OpenAI-compatible client for OpenRouter (/chat/completions)."""

    provider = "openrouter"

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://openrouter.ai/api/v1",
        timeout: int = 600,
        site_url: str = "https://github.com/Sber-mkn/hyperagent",
        app_name: str = "hyperagent-v3",
    ):
        if not api_key:
            raise RuntimeError("OPENROUTER_API_KEY is not set")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": site_url,
            "X-Title": app_name,
        }

    def _post(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        url = f"{self.base_url}/chat/completions"
        last_response: requests.Response | None = None

        for attempt in range(1, _MAX_RETRIES + 1):
            response = requests.post(
                url,
                headers=self.headers,
                json=payload,
                timeout=(10, self.timeout),
            )
            last_response = response

            if response.status_code in _RETRYABLE_STATUS:
                wait_s = min(2**attempt, 60)
                logger.warning(
                    "OpenRouter HTTP %s — retry %d/%d in %ds",
                    response.status_code,
                    attempt,
                    _MAX_RETRIES,
                    wait_s,
                )
                time.sleep(wait_s)
                continue

            response.raise_for_status()
            return response.json()

        if last_response is not None:
            last_response.raise_for_status()
        raise RuntimeError("OpenRouter request failed with no response")

    def send(self, chat: LLMChat, **kwargs) -> LLMChat:
        payload = {
            "messages": chat.to_payload(),
            "stream": False,
            "max_tokens": kwargs.pop("max_tokens", 512),
            **kwargs,
        }
        data = self._post(payload)
        if "error" in data and "choices" not in data:
            err = data["error"]
            msg = err.get("message", err) if isinstance(err, dict) else str(err)
            raise RuntimeError(f"OpenRouter error: {msg}")
        return chat + LLMMessage.from_openai_response(data, self.provider)

    def stream(
        self,
        chat: LLMChat,
        on_chunk_think: Optional[Callable[[str], None]],
        on_chunk_content: Optional[Callable[[str], None]],
        **kwargs,
    ) -> LLMChat:
        # Non-streaming fallback — sufficient for the V3 agent loop.
        reply = self.send(chat, **kwargs)
        last = reply[-1]
        if on_chunk_content and last.content:
            on_chunk_content(last.content)
        if on_chunk_think and last.thinking:
            on_chunk_think(last.thinking)
        return reply
