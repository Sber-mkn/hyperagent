from enum import StrEnum
from typing import Literal

from pydantic import BaseModel

from contracts.git_commands import GitCommand


class RequestType(StrEnum):
    GIT = "git"
    AGENT_EVENT = "agent_event"
    WORKER_RESULT = "worker_result"


class GitRequest(BaseModel):
    type: Literal[RequestType.GIT] = RequestType.GIT
    command: GitCommand
