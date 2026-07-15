from contracts.git_commands import (
    GitCommitCommand,
    GitDiffCommand,
    GitRollbackCommand,
    GitStatusCommand,
)
from contracts.requests import GitRequest
from database.crud import add_error, get_snapshot_by_status, update_snapshot_status
from supervisor.git_service import GitService
from supervisor.rollback import start_agent


def mark_pending_snapshot_stable() -> None:
    snapshot = get_snapshot_by_status("PENDING")
    if snapshot:
        snapshot_id, _, _ = snapshot
        update_snapshot_status(snapshot_id, "STABLE")


def error_handler(message: dict, git_service: GitService):
    error_text = message.get("error")

    snapshot = get_snapshot_by_status("PENDING")
    if snapshot:
        snapshot_id, snapshot_sha, snapshot_message = snapshot
        add_error(snapshot_id, error_text)
        update_snapshot_status(snapshot_id, "ERROR")
    stable_snapshot = get_snapshot_by_status("STABLE")
    if not stable_snapshot:
        raise ValueError("Database has not STABLE snapshot")
    _, snapshot_sha, _ = stable_snapshot
    git_service.rollback(snapshot_sha)
    start_agent()

    return error_text


def ack_handler(git_service: GitService):
    mark_pending_snapshot_stable()

    git_service.check()


def git_handler(message: dict, git_service: GitService) -> dict | None:
    request = GitRequest.model_validate(message)
    command = request.command

    result = ""

    if isinstance(command, GitStatusCommand):
        result = git_service.status()
    elif isinstance(command, GitDiffCommand):
        result = git_service.diff(command.hash)
    elif isinstance(command, GitCommitCommand):
        compile_error = git_service.compile_python_files()
        if compile_error:
            return {"error": compile_error}

        mark_pending_snapshot_stable()
        git_service.add()
        if git_service.commit(command.message):
            return {"restart_agent": True}
        else:
            return {"error": "no changes to commit"}
    elif isinstance(command, GitRollbackCommand):
        result = git_service.rollback(command.target_sha)

    return {"stdout": result}
