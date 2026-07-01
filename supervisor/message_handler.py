import json

from contracts.git_commands import (
    GitAddPathsCommand,
    GitCommitCommand,
    GitDiffCommand,
    GitRollbackCommand,
    GitStagedDiffCommand,
    GitStatusCommand,
)
from contracts.requests import GitRequest
from database.crud import add_error, add_snapshot, get_snapshot_by_status, update_snapshot_status
from supervisor.git_service.git_service import AgentGitService

def error_handler(message: json):
    error_text = message.get("error")
    snapshot = get_snapshot_by_status("PENDING")
    if snapshot:
        snapshot_id, snapshot_sha, snapshot_message = snapshot
        add_error(snapshot_id, error_text)
        update_snapshot_status(snapshot_id, "ERROR")
    stable_snapshot = get_snapshot_by_status("STABLE")
    if not stable_snapshot:
        raise ValueError("Database has not STABLE snapshot")
    _, snapshot_sha, snapshot_text = stable_snapshot
    return snapshot_sha, snapshot_text

def commit_handler(message: json):
    commit_sha = message.get("commit_sha")
    commit_text = message.get("commit_text")
    add_snapshot(commit_sha, "PENDING", commit_text)


def ack_handler():
    snapshot = get_snapshot_by_status("PENDING")
    if snapshot:
        snapshot_id, _, _ = snapshot
        update_snapshot_status(snapshot_id, "STABLE")

def git_handler(message: dict, publisher) -> None:
    request = GitRequest.model_validate(message)
    git_service = AgentGitService(publisher)
    command = request.command

    if isinstance(command, GitStatusCommand):
        git_service.status()
    elif isinstance(command, GitDiffCommand):
        git_service.diff()
    elif isinstance(command, GitStagedDiffCommand):
        git_service.staged_diff()
    elif isinstance(command, GitAddPathsCommand):
        git_service.add_paths(command.paths)
    elif isinstance(command, GitCommitCommand):
        git_service.commit(command.message, paths=command.paths)
    elif isinstance(command, GitRollbackCommand):
        git_service.rollback(command.target_sha)
