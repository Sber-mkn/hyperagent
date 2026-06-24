from dataclasses import dataclass, field
from typing import Optional, Any, Iterator

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
class StreamChunk:
    """Один чанк потока: thinking-токен или content-токен."""
    type: str # "thinking" | "content"
    text: str

    @property
    def is_thinking(self) -> bool:
        return self.type == "thinking"

    @property
    def is_content(self) -> bool:
        return self.type == "content"

    def __str__(self) -> str:
        return self.text


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


class LLMStreamingResponse:
    """Класс для итерации потока строк-чанков. После полного прохода
    доступен .response с финальным LLMResponse."""

    def __init__(self, generator: Iterator[str]):
        self._generator = generator
        self.response: Optional[LLMResponse] = None

    def __iter__(self) -> Iterator[str]:
        return self._generator