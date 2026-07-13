from pydantic import BaseModel, ConfigDict
from typing import Optional, List, Dict, Any
from datetime import datetime

class LLMMessageSchema(BaseModel):
    id: int
    done: bool = True
    done_reason: Optional[str] = None
    role: str
    thinking: str = ""
    content: str = ""

    tool_calls: Optional[List[Dict[str, Any]]] = None
    tool_call_id: Optional[str] = None
    provider: str = ""
    model: str = ""

    tokens_prompt: Optional[int] = None
    tokens_response: Optional[int] = None
    duration_load: Optional[int] = None
    duration_prompt: Optional[int] = None
    duration_response: Optional[int] = None

    dt: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)