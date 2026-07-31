import logging
import os
import pathlib
import shutil
import subprocess
import tokenize

from database.crud import add_snapshot, get_stable_snapshots
from supervisor.git_service.git_types import GitError, GitResult

GIT_DIR = pathlib.Path("/hyperagent/agent_git")
GIT_WORK_TREE = pathlib.Path("/hyperagent/agent")
GIT_BRANCH = "main"

logger = logging.getLogger(__name__)


class GitService:
    def __init__(
        self,
        repo_dir: pathlib.Path = GIT_DIR,
        timeout_seconds: int = 30,
    ):

        self.repo_dir = repo_dir.resolve()
        self.git_work_tree = GIT_WORK_TREE.resolve()
        self.branch = GIT_BRANCH
        self.timeout_seconds = timeout_seconds

        self.git_env = os.environ.copy()
        self.git_env["GIT_DIR"] = str(repo_dir)
        self.git_env["GIT_WORK_TREE"] = str(GIT_WORK_TREE)

        self._init_repo()

    def _init_repo(self) -> None:
        self._ensure_repo_init()
        self._ensure_branch()
        self._commit_agent_path()

    def _ensure_repo_init(self) -> None:
        if not self.is_inside_work_tree():
            logger.info("Repository does not exists")

            self._del_exists_repo_dir()
            self._init_commands()

    def _del_exists_repo_dir(self) -> None:
        if self.repo_dir.exists():
            for item in self.repo_dir.iterdir():
                if item.is_dir():
                    shutil.rmtree(item)
                else:
                    item.unlink()

            logger.info("Repository dir has been cleared")

        else:
            logger.warning("Repository dir does not exists")
            self.repo_dir.mkdir(parents=True, exist_ok=True)

    def _ensure_branch(self) -> None:
        if self.current_branch() != self.branch:
            if self.is_branch_exists():
                self.switch_branch()
            else:
                self.create_branch()

    def _commit_agent_path(self) -> None:
        if not self.has_commit():
            logger.info("Repository has no commits")

            self.add()
            self.commit("Initial commit", allow_empty=True, is_stable=True)

        else:
            logger.info("Repository has commits")

            # Код, с которым стартовал контейнер, — базовая версия, а не
            # непроверенная правка агента.
            self.check(is_stable=True)

    def check(self, is_stable: bool = False):
        self.add()
        if self.status():
            self.commit("Uncommited changes", is_stable=is_stable)

    def has_commit(self) -> bool:
        logger.info(self._current_revision_command().return_code)
        return self._current_revision_command().return_code == 0

    @staticmethod
    def build_git_command(command: list[str]) -> list[str]:
        return ["git", *command]

    def run_git_command(self, command: list[str], check: bool = True) -> GitResult:
        process = subprocess.run(
            self.build_git_command(command),
            cwd=self.repo_dir,
            capture_output=True,
            text=True,
            timeout=self.timeout_seconds,
            check=check,
            env=self.git_env,
        )

        result = GitResult(
            args=command,
            stdout=process.stdout,
            stderr=process.stderr,
            return_code=process.returncode,
        )

        return result

    def run_git_commands(self, commands: list[list[str]], check: bool = True) -> list[GitResult]:
        result = []
        for command in commands:
            result.append(self.run_git_command(command, check))

        return result

    def validate_relative_path(self, path: str) -> str:
        candidate = (self.git_work_tree / path).resolve()

        try:
            relative_path = candidate.relative_to(self.git_work_tree)
        except ValueError as exc:
            raise GitError(f"Path escapes repository root: {path}") from exc

        return relative_path.as_posix()

    def is_inside_work_tree(self) -> bool:
        result = self.run_git_command(["rev-parse", "--is-inside-work-tree"], check=False)
        return result.return_code == 0

    def _init_commands(self) -> None:
        self.run_git_commands(
            [
                ["init", str(self.repo_dir)],
                ["config", "user.email", "agent@hyper.local"],
                ["config", "user.name", "Hyper Agent"],
            ]
        )

    def is_branch_exists(self) -> bool:
        result = self.run_git_command(
            ["show-ref", "--verify", "--quiet", f"refs/heads/{self.branch}"], check=False
        )
        return result.return_code == 0

    def switch_branch(self) -> None:
        self.run_git_command(["switch", self.branch])

    def create_branch(self) -> None:
        self.run_git_command(["switch", "-c", self.branch])

    def rollback(self, target_sha: str) -> str:
        results = self.run_git_commands(
            [
                ["restore", "--source", target_sha, "--staged", "--worktree", "."],
                ["clean", "-fd"],
            ]
        )
        return "\n".join(f"{result.stdout}{result.stderr}" for result in results).strip()

    def status(self) -> str:
        return self.run_git_command(["status", "--porcelain"]).stdout

    def diff(self, _hash: str | None = None) -> str:
        if _hash is not None:
            return self.run_git_command(["show", "--format=", "--patch", _hash]).stdout

        return self.run_git_command(["diff"]).stdout

    def staged_diff(self) -> None:
        self.run_git_command(["diff", "--cached"])

    def add_paths(self, paths: list[str]) -> None:
        if not paths:
            raise GitError("No paths provided for git add")

        safe_paths = [self.validate_relative_path(path) for path in paths]

        self.run_git_command(["add", "--", *safe_paths])

    def add(self) -> str:
        return self.run_git_command(["add", "."]).stdout

    def commit(
        self,
        message: str,
        paths: list[str] | None = None,
        allow_empty: bool = False,
        is_stable: bool = False,
    ) -> bool:
        if paths:
            self.add_paths(paths)
        else:
            self.add()

        status = self.status()
        if not status.strip() and not allow_empty:
            logger.info("No changes to commit, skipping")
            return False

        status = "STABLE" if is_stable else "PENDING"

        command_list = ["commit", "-m", message]
        if allow_empty:
            command_list.append("--allow-empty")

        self.run_git_command(command_list)

        sha = self.current_revision()
        if sha:
            add_snapshot(sha, status, message)

        return True

    @staticmethod
    def log() -> dict:
        return get_stable_snapshots()

    def current_branch(self) -> str:
        return self._current_branch_command().stdout.strip()

    def _current_branch_command(self) -> GitResult:
        return self.run_git_command(["branch", "--show-current"])

    def current_revision(self) -> str:
        return self._current_revision_command().stdout.strip()

    def _current_revision_command(self) -> GitResult:
        return self.run_git_command(["rev-parse", "--verify", "HEAD^{commit}"], check=False)

    def clean_untracked_files(self) -> None:
        self.run_git_command(["clean", "-fd"])

    def compile_python_files(self) -> str | None:
        for path in self.git_work_tree.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue

            relative_path = path.relative_to(self.git_work_tree).as_posix()
            try:
                with tokenize.open(path) as file:
                    source = file.read()
                compile(source, str(path), "exec")
            except SyntaxError as exc:
                location = f"{relative_path}:{exc.lineno or 0}:{exc.offset or 0}"
                source_line = (exc.text or "").strip()
                if source_line:
                    return f"{location}: {exc.msg}\n{source_line}"
                return f"{location}: {exc.msg}"
            except Exception as exc:
                return f"{relative_path}: {type(exc).__name__}: {exc}"

        return None
