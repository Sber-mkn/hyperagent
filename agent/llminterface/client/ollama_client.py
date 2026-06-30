from agent.llminterface.llm_client import LLMClient
from agent.llminterface.llm_response import LLMStreamingResponse, LLMResponse, Usage, Timing, StreamChunk, Iterator

import time
from typing import Optional, Any, Dict, List
import re
import requests
import json


def parse_keep_alive(value: str | int | float) -> float:
    """Преобразование keep_alive в секунды"""
    if isinstance(value, (int, float)):
        return float(value)

    value = value.strip()

    if value in ("-1", "-1s", "-1m", "-1h"):
        return -1.0

    units = {
        "ms": 0.001,
        "s": 1,
        "m": 60,
        "h": 3600,
    }

    pattern = re.compile(r"(\d+(?:\.\d+)?)(ms|s|m|h)")
    matches = pattern.findall(value)

    if not matches:
        raise ValueError(f"Невозможно распарсить keep_alive: {value!r}")

    total_seconds = 0.0
    for number, unit in matches:
        total_seconds += float(number) * units[unit]

    return total_seconds


class OllamaClient(LLMClient):
    """Класс для работы с моделями развёрнутыми в Ollama"""

    # Параметры, которые Ollama ожидает на верхнем уровне запроса.
    TOP_LEVEL_KEYS = {"think", "format", "keep_alive", "logprobs", "top_logprobs"}

    def __init__(
            self,
            url: str,
            model: str,
            **kwargs: int | float | str | bool
    ):
        self.__url: str = url
        self.model: str = model

        self.__last_active: float = time.time()
        self.__time_start_session: float = time.time()
        self.__time_end_session: float = time.time()

        self.default_top, self.default_options = self._split_params(kwargs)

        self.__default_keep_alive_second = 300

    @staticmethod
    def _split_params(params: Dict[str, Any]) -> tuple[Dict[str, Any], Dict[str, Any]]:
        """Разделение произвольного набора параметров на верхнеуровневые и параметры модели по списку TOP_LEVEL_KEYS."""
        top: Dict[str, Any] = {}
        options: Dict[str, Any] = {}
        for key, value in params.items():
            if key in OllamaClient.TOP_LEVEL_KEYS:
                top[key] = value
            else:
                options[key] = value
        return top, options

    def _build_payload(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]],
        stream: bool,
        kwargs: Dict[str, Any],
    ) -> tuple[Dict[str, Any], Optional[str | int | float]]:
        """Сборка payload, накладывая kwargs запроса поверх дефолтов клиента."""
        request_top, request_options = self._split_params(kwargs)

        merged_top = {**self.default_top, **request_top}
        merged_options = {**self.default_options, **request_options}

        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": stream,
        }

        if tools:
            payload["tools"] = tools
        if merged_options:
            payload["options"] = merged_options

        payload.update(merged_top)  # think, format, keep_alive, logprobs, top_logprobs

        return payload, merged_top.get("keep_alive")

    def _update_session_timers(self, keep_alive: Optional[str | int | float]) -> None:
        self.__last_active = time.time()
        if keep_alive is not None:
            self.__time_end_session = self.__last_active + parse_keep_alive(keep_alive)
        else:
            self.__time_end_session = self.__last_active + self.__default_keep_alive_second

    @property
    def time_alive(self) -> float | None:
        if time.time() < self.__time_end_session:
            return time.time() - self.__time_start_session
        return None

    @property
    def keep_alive(self) -> float | None:
        if time.time() < self.__time_end_session:
            return self.__time_end_session - time.time()
        return None

    def chat(
            self,
            messages: List[Dict[str, Any]],
            tools: Optional[List[Dict[str, Any]]] = None,
            timeout: int = 120,
            **kwargs: int | float | str | bool
    ) -> LLMResponse:
        """Отправка запроса модели с последующим получением LLMResponse в качестве ответа"""
        payload, keep_alive = self._build_payload(messages, tools, stream=False, kwargs=kwargs)

        response = requests.post(self.__url, json=payload, timeout=timeout)
        response.raise_for_status()
        data = response.json()

        self._update_session_timers(keep_alive)

        return LLMResponse(
            content=data["message"]["content"],
            model=data.get("model", self.model),
            usage=Usage(
                prompt_tokens=data.get("prompt_eval_count", 0),
                completion_tokens=data.get("eval_count", 0),
                total_tokens=data.get("prompt_eval_count", 0) + data.get("eval_count", 0),
            ),
            timing=Timing.from_ollama(data),
            finish_reason=data.get("done_reason"),
            thinking=data["message"].get("thinking"),
            tool_calls=data["message"].get("tool_calls"),
            raw=data,
        )

    def stream(
            self,
            messages: List[Dict[str, Any]],
            tools: Optional[List[Dict[str, Any]]] = None,
            timeout: int = 120,
            **kwargs: int | float | str | bool
    ) -> LLMStreamingResponse:
        """Отправка запроса модели с получением итератора по чанкам-строкам ответа"""
        def generator() -> Iterator[StreamChunk]:
            payload, keep_alive = self._build_payload(messages, tools, stream=True, kwargs=kwargs)

            with requests.post(self.__url, json=payload, timeout=timeout, stream=True) as response:
                response.raise_for_status()
                content_parts: list[str] = []
                thinking_parts: list[str] = []
                tool_calls: list[dict] = []

                for line in response.iter_lines():
                    if not line:
                        continue
                    chunk = json.loads(line)

                    # tool_calls в стриме приходят в промежуточном чанке, а не в done — копим из любого
                    chunk_tool_calls = chunk.get("message", {}).get("tool_calls")
                    if chunk_tool_calls:
                        tool_calls.extend(chunk_tool_calls)

                    if chunk.get("done"):
                        self._update_session_timers(keep_alive)

                        # Собираем финальный LLMResponse из последнего чанка
                        wrapper.response = LLMResponse(
                            content="".join(content_parts),
                            model=chunk.get("model", self.model),
                            usage=Usage(
                                prompt_tokens=chunk.get("prompt_eval_count", 0),
                                completion_tokens=chunk.get("eval_count", 0),
                                total_tokens=chunk.get("prompt_eval_count", 0) + chunk.get("eval_count", 0),
                            ),
                            timing=Timing.from_ollama(chunk),
                            finish_reason=chunk.get("done_reason"),
                            thinking="".join(thinking_parts) or None,
                            tool_calls=tool_calls or None,
                            raw=chunk,
                        )
                        break

                    message = chunk.get("message", {})

                    thinking = message.get("thinking")
                    if thinking:
                        thinking_parts.append(thinking)
                        yield StreamChunk("thinking", thinking)

                    content = message.get("content", "")
                    if content:
                        content_parts.append(content)
                        yield StreamChunk("content", content)

        wrapper = LLMStreamingResponse(generator())
        return wrapper

    def unload_model(self, timeout: int = 120) -> None:
        """Выгрузка модели из памяти"""
        response = requests.post(
            self.__url,
            json={
                "model": self.model,
                "prompt": "",
                "keep_alive": 0
            },
            timeout=timeout
        )
        response.raise_for_status()
