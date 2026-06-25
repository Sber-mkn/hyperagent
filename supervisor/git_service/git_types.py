from dataclasses import dataclass


class GitError(RuntimeError):
    pass


@dataclass(frozen=True)
class GitResult:
    args: list[str]
    stdout: str
    stderr: str
    returned_code: int
