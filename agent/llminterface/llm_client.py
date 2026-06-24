import requests
import json
from typing import List, Dict, Any, Optional, Iterator
import time
import re

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import pprint


def parse_keep_alive(value: str | int | float) -> float:
    """Преобразует keep_alive в секунды"""
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


@dataclass
class Usage:
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int

    @classmethod
    def empty(cls) -> "Usage":
        return cls(prompt_tokens=0, completion_tokens=0, total_tokens=0)


@dataclass
class Timing:
    total_seconds: float
    load_seconds: float
    prompt_eval_seconds: float
    eval_seconds: float

    @classmethod
    def from_ollama(cls, data: dict) -> "Timing":
        return cls(
            total_seconds=data.get("total_duration", 0) / 1e9,
            load_seconds=data.get("load_duration", 0) / 1e9,
            prompt_eval_seconds=data.get("prompt_eval_duration", 0) / 1e9,
            eval_seconds=data.get("eval_duration", 0) / 1e9,
        )


@dataclass
class LLMResponse:
    content: str
    model: str
    usage: Usage
    timing: Optional[Timing] = None
    finish_reason: Optional[str] = None
    thinking: Optional[str] = None
    tool_calls: Optional[list[dict[str, Any]]] = None
    raw: dict[str, Any] = field(default_factory=dict)


class StreamingResponse:
    """Класс для итерации потока строк-чанков. После полного прохода
    доступен .response с финальным LLMResponse."""

    def __init__(self, generator: Iterator[str]):
        self._generator = generator
        self.response: Optional[LLMResponse] = None

    def __iter__(self) -> Iterator[str]:
        return self._generator


OLLAMA_URL = "http://localhost:11434/api/chat"
DEFAULT_KEEP_ALIVE_SECONDS = 300


class LLMClient(ABC):
    """Класс для работы с разными провайдерами LLM моделей"""
    @abstractmethod
    def chat(
            self,
            messages: List[Dict[str, Any]],
            tools: Optional[List[Dict[str, Any]]] = None,
            timeout: int = 120,
            **kwargs: int | float | str | bool
    ) -> LLMResponse:
        ...

    @abstractmethod
    def stream(
            self,
            messages: List[Dict[str, Any]],
            tools: Optional[List[Dict[str, Any]]] = None,
            timeout: int = 120,
            **kwargs: int | float | str | bool
    ) -> StreamingResponse:
        ...

    @property
    @abstractmethod
    def time_alive(self) -> float | None:
        ...

    @property
    @abstractmethod
    def keep_alive(self):
        ...


class OllamaClient(LLMClient):
    """Класс для работы с моделями развёрнутыми в Ollama"""

    # Параметры, которые Ollama ожидает на верхнем уровне запроса.
    TOP_LEVEL_KEYS = {"think", "format", "keep_alive", "logprobs", "top_logprobs"}

    def __init__(self, url: str, model: str, **kwargs: int | float | str | bool):
        self.__url: str = url
        self.model: str = model

        self.__last_active: float = time.time()
        self.__time_start_session: float = time.time()
        self.__time_end_session: float = time.time()

        self.default_top, self.default_options = self._split_params(kwargs)

    @staticmethod
    def _split_params(
        params: Dict[str, Any]
    ) -> tuple[Dict[str, Any], Dict[str, Any]]:
        """Делит произвольный набор параметров на верхнеуровневые и параметры модели (options) по списку
        TOP_LEVEL_KEYS."""
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
        """Собирает payload, накладывая kwargs запроса поверх дефолтов клиента."""
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
            self.__time_end_session = self.__last_active + DEFAULT_KEEP_ALIVE_SECONDS

    @property
    def time_alive(self) -> float | None:
        if time.time() < self.__time_end_session:
            return time.time() - self.__time_start_session
        return None

    @property
    def keep_alive(self) -> float:
        if time.time() < self.__time_end_session:
            return self.__time_end_session - time.time()

    def chat(
            self,
            messages: List[Dict[str, Any]],
            tools: Optional[List[Dict[str, Any]]] = None,
            timeout: int = 120,
            **kwargs: int | float | str | bool
    ) -> LLMResponse:
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
    ) -> StreamingResponse:
        def generator() -> Iterator[str]:
            payload, keep_alive = self._build_payload(messages, tools, stream=True, kwargs=kwargs)

            with requests.post(self.__url, json=payload, timeout=timeout, stream=True) as response:
                response.raise_for_status()
                content_parts: list[str] = []

                for line in response.iter_lines():
                    if not line:
                        continue
                    chunk = json.loads(line)

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
                            raw=chunk,
                        )
                        break

                    content = chunk.get("message", {}).get("content", "")
                    if content:
                        content_parts.append(content)
                        yield content

        wrapper = StreamingResponse(generator())
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


if __name__ == "__main__":
    # think и keep_alive — верхнеуровневые, temperature — параметр модели
    ollama: LLMClient = OllamaClient(
        OLLAMA_URL, "gemma4:e2b",
        temperature=0.5, keep_alive="2m", num_ctx=16384, think=False
    )
    print((ollama.time_alive, ollama.keep_alive))

    stream = ollama.stream([
        {"role": "system", "content": "Всегда отвечай ровно за 10 предложений"},
        {"role": "user", "content": "Привет, что такое автошкола?"}
    ])

    for chunk in stream:
        print(chunk, end="", flush=True)
    print()

    pprint.pprint(stream.response)
    print((ollama.time_alive, ollama.keep_alive))

