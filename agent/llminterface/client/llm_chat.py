import datetime
from collections import UserList
from typing import Any, Literal, NotRequired, TypedDict

from pydantic import BaseModel


class Message(TypedDict):
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    tool_calls: NotRequired[list[dict]]
    tool_call_id: NotRequired[str]


class LLMTokens(BaseModel):
    prompt: int | None
    response: int | None

    @property
    def total(self) -> int | None:
        return self.prompt + self.response


class LLMDuration(BaseModel):
    """Длительности этапов в секундах (дробные)."""

    load: float | None
    prompt: float | None
    response: float | None

    @property
    def total(self) -> float | None:
        return self.load + self.prompt + self.response


class LLMMessage(BaseModel):
    done: bool
    done_reason: str | None = None

    role: str
    thinking: str
    content: str

    tool_calls: list[dict] | None = None
    tool_call_id: str | None = None

    provider: str = ""
    model: str = ""

    tokens: LLMTokens | None = None
    duration: LLMDuration | None = None

    dt: datetime.datetime | None = None

    @classmethod
    def from_message(cls, message: Message):
        return cls(
            done=True,
            role=message.get("role", "assistant"),
            thinking="",
            content=message.get("content", ""),
            dt=datetime.datetime.now(),
        )

    @classmethod
    def tool_result(cls, name: str, content: Any, tool_call_id: str | None = None) -> LLMMessage:
        return cls(
            done=True,
            role="tool",
            thinking="",
            content=f"[{name}] {content}",
            tool_call_id=tool_call_id,
            dt=datetime.datetime.now(),
        )


class LLMChat(UserList):
    def __init__(self, initlist=None):
        messages: list[LLMMessage] = []
        for i in initlist or []:
            if isinstance(i, LLMMessage):
                messages.append(i)
            elif isinstance(i, dict):
                _message = Message(role=i.get("role", "assistant"), content=i.get("content", ""))
                messages.append(LLMMessage.from_message(_message))
            else:
                raise TypeError(
                    f"LLMChat принимает только LLMMessage и dict, получено: {type(i).__name__}"
                )
        super().__init__(messages)

    def to_payload(self) -> list[Message]:
        payload = []
        for m in self.data:
            msg = Message(role=m.role, content=m.content)
            if m.tool_calls:
                msg["tool_calls"] = m.tool_calls
            if m.tool_call_id:
                msg["tool_call_id"] = m.tool_call_id
            payload.append(msg)
        return payload

    def __add__(self, other: LLMMessage | LLMChat) -> LLMChat:
        if isinstance(other, LLMChat):
            return LLMChat(self.data + other.data)
        return LLMChat([*self.data, other])

    def __radd__(self, other: LLMMessage | LLMChat) -> LLMChat:
        if isinstance(other, LLMChat):
            return LLMChat(other.data + self.data)
        return LLMChat([other, *self.data])

    def __iadd__(self, other: LLMMessage) -> LLMChat:
        self.append(other)
        return self
