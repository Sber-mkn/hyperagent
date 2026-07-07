from typing import Any, List, Dict, Optional, Literal, TypedDict, NotRequired

from pydantic import BaseModel
from collections import UserList

import datetime


class Message(TypedDict):
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    tool_calls: NotRequired[List[Dict]]
    tool_call_id: NotRequired[str]

class LLMTokens(BaseModel):
    prompt: Optional[int]
    response: Optional[int]

    @property
    def total(self) -> Optional[int]:
        return self.prompt + self.response



class LLMDuration(BaseModel):
    load: Optional[int]
    prompt: Optional[int]
    response: Optional[int]

    @property
    def total(self) -> Optional[int]:
        return self.load + self.prompt + self.response


class LLMMessage(BaseModel):
    done: bool
    done_reason: Optional[str] = None

    role: str
    thinking: str
    content: str

    tool_calls: Optional[List[Dict]] = None       # запрошенные вызовы инструментов
    tool_call_id: Optional[str] = None            # для role="tool": id вызова, на который отвечаем

    provider: str = ""
    model: str = ""

    tokens: Optional[LLMTokens] = None
    duration: Optional[LLMDuration] = None

    dt: Optional[datetime.datetime] = None

    @classmethod
    def from_message(cls, message: Message):
        return cls(
            done=True,
            role=message.get("role", "assistant"),
            thinking="",
            content=message.get("content", ""),
            dt=datetime.datetime.now()
        )

    @classmethod
    def tool_result(cls, name: str, content: Any, tool_call_id: Optional[str] = None) -> "LLMMessage":
        # результат выполнения инструмента как сообщение роли "tool".
        # tool_call_id обязателен для openai, в ollama игнорируется.
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
        messages: List[LLMMessage] = []
        for i in initlist or []:
            if isinstance(i, LLMMessage):
                messages.append(i)
            elif isinstance(i, dict):
                _message = Message(
                    role=i.get("role", "assistant"),
                    content=i.get("content", "")
                )
                messages.append(LLMMessage.from_message(_message))
            else:
                raise TypeError(
                    f"LLMChat принимает только LLMMessage и dict, получено: {type(i).__name__}"
                )
        super().__init__(messages)




    def to_payload(self) -> List[Message]:
        payload = []
        for m in self.data:
            msg = Message(role=m.role, content=m.content)
            if m.tool_calls:
                msg["tool_calls"] = m.tool_calls
            if m.tool_call_id:
                msg["tool_call_id"] = m.tool_call_id
            payload.append(msg)
        return payload

    def __add__(self, other: "LLMMessage | LLMChat") -> "LLMChat":
        if isinstance(other, LLMChat):
            return LLMChat(self.data + other.data)
        return LLMChat(self.data + [other])

    def __radd__(self, other: "LLMMessage | LLMChat") -> "LLMChat":
        if isinstance(other, LLMChat):
            return LLMChat(other.data + self.data)
        return LLMChat([other] + self.data)

    def __iadd__(self, other: LLMMessage) -> "LLMChat":
        self.append(other)
        return self