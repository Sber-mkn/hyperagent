import pathlib
import subprocess

REPO_DIR = pathlib.Path("/hyperagent/agent")


class CommandWorker:
    def __init__(self, repo_dir: pathlib.Path = REPO_DIR, timeout_seconds: int = 30):
        self.repo_dir = repo_dir.resolve()
        self.timeout_seconds = timeout_seconds

    def run_command(self, command: list[str]) -> None:
        subprocess.run(
            command,
            cwd=self.repo_dir,
            capture_output=True,
            text=True,
            timeout=self.timeout_seconds,
            check=True,
        )

    def run_commands(self, commands: list[list[str]]) -> None:
        for command in commands:
            self.run_command(command)


def execute_command(command: list[str] | list[list[str]]) -> None:
    worker = CommandWorker()
    if command and isinstance(command[0], list):
        worker.run_commands(command)
    else:
        worker.run_command(command)
