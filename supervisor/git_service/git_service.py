import logging
import pathlib

from contracts.requests import RequestType
from supervisor.git_service.git_types import GitError
from supervisor.rabbitmq_service.rabbitmq_supervisor import RabbitMQService

REPO_DIR: pathlib.Path = pathlib.Path.home() / "hyperagent/agent"

logger = logging.getLogger(__name__)


class BaseGitService:
    def __init__(
        self,
        publisher: RabbitMQService,
        repo_dir: pathlib.Path = REPO_DIR,
        timeout_seconds: int = 30,
    ):

        self.publisher = publisher
        self.repo_dir = repo_dir.resolve()
        self.timeout_seconds = timeout_seconds

    @staticmethod
    def build_git_command(command: list[str]) -> list[str]:
        return ["git", *command]

    def run_git_command(self, command: list[str]) -> None:
        self.run_git_commands([command])

    def run_git_commands(self, commands: list[list[str]]) -> None:
        message = {
            "type": RequestType.GIT,
            "command": [self.build_git_command(command) for command in commands],
        }
        # self.publisher.publish_message(message)

    def validate_relative_path(self, path: str) -> str:
        candidate = (self.repo_dir / path).resolve()

        try:
            relative_path = candidate.relative_to(self.repo_dir)
        except ValueError as exc:
            raise GitError(f"Path escapes repository root: {path}") from exc

        return relative_path.as_posix()

    def rollback(self, target_sha: str) -> None:
        self.run_git_commands(
            [
                ["restore", "--source", target_sha, "--staged", "--worktree", "."],
                ["clean", "-fd"],
            ]
        )


class AgentGitService(BaseGitService):
    def status(self) -> None:
        self.run_git_command(["status", "--porcelain"])

    def diff(self) -> None:
        self.run_git_command(["diff"])

    def staged_diff(self) -> None:
        self.run_git_command(["diff", "--cached"])

    def add_paths(self, paths: list[str]) -> None:
        if not paths:
            raise GitError("No paths provided for git add")

        safe_paths = [self.validate_relative_path(path) for path in paths]

        self.run_git_command(["add", "--", *safe_paths])

    def commit(self, message: str, paths: list[str] | None = None) -> None:
        if paths:
            self.add_paths(paths)

        self.run_git_command(
            [
                "-c",
                "user.name=Self Agent",
                "-c",
                "user.email=self-agent@example.local",
                "commit",
                "-m",
                message,
            ]
        )


class SupervisorGitService(BaseGitService):
    def current_branch(self) -> None:
        return self.run_git_command(["branch", "--show-current"])

    def current_revision(self) -> None:
        return self.run_git_command(["rev-parse", "HEAD"])

    def branch_exists(self, branch_name: str) -> bool:
        return True

    def switch_branch(self, branch_name: str) -> None:
        self.run_git_command(["switch", branch_name])

    def create_branch(self, branch_name: str, base_branch: str = "main") -> None:
        self.run_git_command(["switch", "-c", branch_name, base_branch])

    def clean_untracked_files(self) -> None:
        self.run_git_command(["clean", "-fd"])
