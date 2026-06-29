from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, Field

PathType = Annotated[str, Field(min_length=1)]


class GitCommandType(StrEnum):
    STATUS = "status"
    DIFF = "diff"
    STAGED_DIFF = "staged_diff"
    ADD_PATHS = "add_paths"
    COMMIT = "commit"
    ROLLBACK = "rollback"


class SupervisorCommandType(StrEnum):
    GET_COMMITS = "get_commits"


class GitStatusCommand(BaseModel):
    command: Literal[GitCommandType.STATUS]


class GitDiffCommand(BaseModel):
    command: Literal[GitCommandType.DIFF]


class GitStagedDiffCommand(BaseModel):
    command: Literal[GitCommandType.STAGED_DIFF]


class GitAddPathsCommand(BaseModel):
    command: Literal[GitCommandType.ADD_PATHS]
    paths: list[PathType] = Field(min_length=1)


class GitCommitCommand(BaseModel):
    command: Literal[GitCommandType.COMMIT]
    message: str = Field(min_length=1)
    paths: list[PathType] = Field(default_factory=list)


class GitRollbackCommand(BaseModel):
    command: Literal[GitCommandType.ROLLBACK]
    target_sha: str = Field(min_length=7, max_length=40)


# TODO: подумать над реализацией получения всех коммитов агентом
class GetCommitsCommand(BaseModel):
    command: Literal[SupervisorCommandType.GET_COMMITS]


GitCommand = Annotated[
    GitStatusCommand
    | GitDiffCommand
    | GitStagedDiffCommand
    | GitAddPathsCommand
    | GitCommitCommand
    | GitRollbackCommand,
    Field(discriminator="command"),
]
