from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, Field

PathType = Annotated[str, Field(min_length=1)]


class GitCommandType(StrEnum):
    STATUS = "status"
    DIFF = "diff"
    COMMIT = "commit"
    ROLLBACK = "rollback"
    LOG = "log"


class GitStatusCommand(BaseModel):
    command: Literal[GitCommandType.STATUS]


class GitDiffCommand(BaseModel):
    command: Literal[GitCommandType.DIFF]
    hash: str | None = Field(default=None, min_length=7, max_length=40, pattern=r"^[0-9a-fA-F]+$")


class GitCommitCommand(BaseModel):
    command: Literal[GitCommandType.COMMIT]
    message: str = Field(min_length=1)


class GitRollbackCommand(BaseModel):
    command: Literal[GitCommandType.ROLLBACK]
    target_sha: str = Field(min_length=7, max_length=40)


class GetStableCommitsCommand(BaseModel):
    command: Literal[GitCommandType.LOG]


GitCommand = Annotated[
    GitStatusCommand
    | GitDiffCommand
    | GitCommitCommand
    | GitRollbackCommand
    | GetStableCommitsCommand,
    Field(discriminator="command"),
]
