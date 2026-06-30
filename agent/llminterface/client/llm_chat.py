from typing import List, Dict, Optional, Literal, TypedDict

from pydantic import BaseModel
from collections import UserList

import datetime


class Message(TypedDict):
    role: Literal["system", "user", "assistant"]
    content: str

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

    provider: str = ""
    model: str = ""

    tokens: Optional[LLMTokens] = None
    duration: Optional[LLMDuration] = None

    dt: Optional[datetime.datetime] = None

    @classmethod
    def from_response(cls, response: dict, provider: str) -> "LLMMessage":
        message = response.get("message", {})

        return cls(
            done=response.get("done", True),
            done_reason=response.get("done_reason"),
            role=message.get("role", "assistant"),
            thinking=message.get("thinking", ""),
            content=message.get("content", ""),
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
    def from_message(cls, message: Message):
        return cls(
            done=True,
            role=message.get("role", "assistant"),
            thinking="",
            content=message.get("content", ""),
            dt=datetime.datetime.now()
        )


class LLMChat(UserList):
    def __init__(self, initlist=None):
        messages: List[LLMMessage] = []
        for i in initlist:
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
        return [Message(role=m.role, content=m.content) for m in self.data]

    def __add__(self, other: LLMMessage) -> "LLMChat":
        return LLMChat(self.data + [other])

    def __iadd__(self, other: LLMMessage) -> "LLMChat":
        self.append(other)
        return self