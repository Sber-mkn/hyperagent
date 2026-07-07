from __future__ import annotations

import datetime
from collections import UserList
from typing import Any, Dict, List, Literal, Optional, TypedDict

from pydantic import BaseModel, Field


class Message(TypedDict, total=False):
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    tool_calls: List[Dict[str, Any]]
    tool_call_id: str


class LLMTokens(BaseModel):
    prompt: Optional[int] = None
    response: Optional[int] = None

    @property
    def total(self) -> Optional[int]:
        if self.prompt is None and self.response is None:
            return None
        return (self.prompt or 0) + (self.response or 0)


class LLMDuration(BaseModel):
    load: Optional[int] = None
    prompt: Optional[int] = None
    response: Optional[int] = None

    @property
    def total(self) -> Optional[int]:
        parts = [self.load, self.prompt, self.response]
        if all(p is None for p in parts):
            return None
        return sum(p or 0 for p in parts)


class LLMMessage(BaseModel):
    done: bool = True
    done_reason: Optional[str] = None

    role: str
    thinking: str = ""
    content: str = ""

    tool_calls: Optional[List[Dict[str, Any]]] = None
    tool_call_id: Optional[str] = None
    name: Optional[str] = None

    provider: str = ""
    model: str = ""

    tokens: Optional[LLMTokens] = None
    duration: Optional[LLMDuration] = None
    dt: Optional[datetime.datetime] = None

    @classmethod
    def from_ollama_response(cls, response: dict, provider: str) -> "LLMMessage":
        message = response.get("message", {})
        return cls(
            done=response.get("done", True),
            done_reason=response.get("done_reason"),
            role=message.get("role", "assistant"),
            thinking=message.get("thinking", ""),
            content=message.get("content", ""),
            tool_calls=message.get("tool_calls"),
            provider=provider,
            model=response.get("model", ""),
            tokens=LLMTokens(
                prompt=response.get("prompt_eval_count"),
                response=response.get("eval_count"),
            ),
            duration=LLMDuration(
                load=response.get("load_duration"),
                prompt=response.get("prompt_eval_duration"),
                response=response.get("eval_duration"),
            ),
            dt=datetime.datetime.now(),
        )

    @classmethod
    def from_openai_response(cls, response: dict, provider: str) -> "LLMMessage":
        choice = (response.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        usage = response.get("usage") or {}
        tool_calls = message.get("tool_calls")
        normalized: Optional[List[Dict[str, Any]]] = None
        if tool_calls:
            normalized = []
            for tc in tool_calls:
                fn = tc.get("function") or {}
                normalized.append(
                    {
                        "id": tc.get("id"),
                        "type": tc.get("type", "function"),
                        "function": {
                            "name": fn.get("name"),
                            "arguments": fn.get("arguments") or "{}",
                        },
                    }
                )
        return cls(
            done=True,
            done_reason=choice.get("finish_reason"),
            role=message.get("role", "assistant"),
            content=message.get("content") or "",
            tool_calls=normalized,
            provider=provider,
            model=response.get("model", ""),
            tokens=LLMTokens(
                prompt=usage.get("prompt_tokens"),
                response=usage.get("completion_tokens"),
            ),
            dt=datetime.datetime.now(),
        )

    @classmethod
    def from_message(cls, message: Message) -> "LLMMessage":
        return cls(
            done=True,
            role=message.get("role", "assistant"),
            content=message.get("content", ""),
            tool_calls=message.get("tool_calls"),
            tool_call_id=message.get("tool_call_id"),
            dt=datetime.datetime.now(),
        )

    @classmethod
    def tool_result(cls, name: str, content: Any, tool_call_id: Optional[str] = None) -> "LLMMessage":
        text = content if isinstance(content, str) else str(content)
        return cls(
            done=True,
            role="tool",
            content=text,
            tool_call_id=tool_call_id,
            name=name,
            dt=datetime.datetime.now(),
        )

    def to_api_message(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"role": self.role, "content": self.content or ""}
        if self.tool_calls:
            payload["tool_calls"] = self.tool_calls
            payload["content"] = self.content or None
        if self.role == "tool":
            if self.tool_call_id:
                payload["tool_call_id"] = self.tool_call_id
            if self.name:
                payload["name"] = self.name
        return payload


class LLMChat(UserList):
    def __init__(self, initlist=None):
        messages: List[LLMMessage] = []
        for item in initlist or []:
            if isinstance(item, LLMMessage):
                messages.append(item)
            elif isinstance(item, dict):
                messages.append(
                    LLMMessage.from_message(
                        Message(
                            role=item.get("role", "assistant"),
                            content=item.get("content", ""),
                            tool_calls=item.get("tool_calls"),
                            tool_call_id=item.get("tool_call_id"),
                        )
                    )
                )
            else:
                raise TypeError(
                    f"LLMChat accepts LLMMessage or dict, got {type(item).__name__}"
                )
        super().__init__(messages)

    def to_payload(self) -> List[Dict[str, Any]]:
        return [m.to_api_message() for m in self.data]

    def __add__(self, other: LLMMessage) -> "LLMChat":
        return LLMChat(self.data + [other])

    def __iadd__(self, other: LLMMessage) -> "LLMChat":
        self.append(other)
        return self

    def total_tokens_estimate(self) -> int:
        return sum(max(1, len(m.content) // 4) for m in self.data)
