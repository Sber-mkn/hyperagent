import pathlib
import subprocess

from git_types import GitError, GitResult

REPO_DIR: pathlib.Path = pathlib.Path.home() / "agent"


class BaseGitService:
    def __init__(
        self,
        repo_dir: pathlib.Path = REPO_DIR,
        timeout_seconds: int = 30,
    ):

        self.repo_dir = repo_dir.resolve()
        self.timeout_seconds = timeout_seconds

    def run_git_command(self, args: list[str]) -> GitResult:
        git_command = ["git", *args]

        process = subprocess.run(
            git_command,
            cwd=self.repo_dir,
            capture_output=True,
            text=True,
            timeout=self.timeout_seconds,
            check=False,
        )

        result = GitResult(
            args=git_command,
            stdout=process.stdout,
            stderr=process.stderr,
            returned_code=process.returncode,
        )

        if process.returncode != 0:
            raise GitError

        return result

    def validate_relative_path(self, path: str) -> str:
        candidate = (self.repo_dir / path).resolve()

        try:
            relative_path = candidate.relative_to(self.repo_dir)
        except ValueError as exc:
            raise GitError(f"Path escapes repository root: {path}") from exc

        return relative_path.as_posix()


class AgentGitService(BaseGitService):
    def status(self) -> str:
        return self.run_git_command(["status", "--porcelain"]).stdout

    def diff(self) -> str:
        return self.run_git_command(["diff"]).stdout

    def staged_diff(self) -> str:
        return self.run_git_command(["diff", "--cached"]).stdout

    def current_branch(self) -> str:
        return self.run_git_command(["branch", "--show-current"]).stdout.strip()

    def current_revision(self) -> str:
        return self.run_git_command(["rev-parse", "HEAD"]).stdout.strip()

    def add_paths(self, paths: list[str]) -> None:
        if not paths:
            raise GitError("No paths provided for git add")

        safe_paths = [self.validate_relative_path(path) for path in paths]

        self.run_git_command(["add", "--", *safe_paths])

    def commit(self, message: str) -> str:
        if not self.staged_diff().strip():
            raise GitError("Cannot commit: no staged changes")

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

        return self.current_revision()


class SupervisorGitService(BaseGitService):
    def current_branch(self) -> str:
        return self.run_git_command(["branch", "--show-current"]).stdout.strip()

    def current_revision(self) -> str:
        return self.run_git_command(["rev-parse", "HEAD"]).stdout.strip()

    def branch_exists(self, branch_name: str) -> bool:
        return True

    def switch_branch(self, branch_name: str) -> None:
        self.run_git_command(["switch", branch_name])

    def create_branch(self, branch_name: str, base_branch: str = "main") -> None:
        self.run_git_command(["switch", "-c", branch_name, base_branch])

    def reset_hard_to_revision(self, revision: str) -> None:
        self.run_git_command(["reset", "--hard", revision])

    def clean_untracked_files(self) -> None:
        self.run_git_command(["clean", "-fd"])
