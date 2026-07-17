from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class LLMMessageSchema(BaseModel):
    id: int
    done: bool = True
    done_reason: str | None = None
    role: str
    thinking: str = ""
    content: str = ""

    tool_calls: list[dict[str, Any]] | None = None
    tool_call_id: str | None = None
    name: str | None = None

    provider: str = ""
    model: str = ""

    tokens_prompt: int | None = None
    tokens_response: int | None = None
    duration_load: int | None = None
    duration_prompt: int | None = None
    duration_response: int | None = None

    dt: datetime | None = None

    model_config = ConfigDict(from_attributes=True)
