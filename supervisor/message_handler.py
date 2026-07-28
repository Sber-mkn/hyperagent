import logging

from contracts.git_commands import (
    GetStableCommitsCommand,
    GitCommitCommand,
    GitDiffCommand,
    GitRollbackCommand,
    GitStatusCommand,
)
from contracts.requests import GitRequest
from database.agent.crud import (
    add_client_message,
    create_chat,
    get_chat_history,
    list_chats,
    rename_chat,
)
from database.crud import add_error, get_snapshot_by_status, update_snapshot_status
from supervisor.git_service import GitService
from supervisor.model_catalog import list_models
from supervisor.rollback import start_agent

logger = logging.getLogger(__name__)


def _short_reason(error: Exception) -> str:
    """Network failures arrive as a paragraph of urllib internals; the client
    shows this next to the model picker, so keep it to the point."""
    text = " ".join(str(error).split())
    if "Connection refused" in text or "Failed to establish a new connection" in text:
        return "соединение отклонено"
    if "timed out" in text.lower():
        return "превышено время ожидания"
    if "Name or service not known" in text or "nodename nor servname" in text:
        return "адрес не разрешается"
    return text[:120] or type(error).__name__


def mark_pending_snapshot_stable() -> None:
    snapshot = get_snapshot_by_status("PENDING")
    if snapshot:
        snapshot_id, _, _ = snapshot
        update_snapshot_status(snapshot_id, "STABLE")


def failure_summary(error_text: str) -> str:
    """Last line of a traceback — the part worth showing a person."""
    lines = [line.strip() for line in (error_text or "").splitlines() if line.strip()]
    return lines[-1][:300] if lines else "неизвестная ошибка"


def error_handler(message: dict, git_service: GitService) -> dict:
    """Roll back only what the agent broke in itself.

    A PENDING snapshot means the agent committed a change to its own source
    that has not proven itself yet — the one case where restoring the previous
    version can actually help. Everything else (the iteration limit, an
    unreachable model, a network blip) is an ordinary task failure: rolling
    back there deleted working code for no reason, and replaying the task
    simply reproduced the failure.
    """
    error_text = message.get("error") or ""

    snapshot = get_snapshot_by_status("PENDING")
    if not snapshot:
        logger.info(
            "Task failed on already-stable code, no rollback: %s", failure_summary(error_text)
        )
        start_agent()
        return {"rolled_back": False, "error_text": error_text}

    snapshot_id, _, _ = snapshot
    add_error(snapshot_id, error_text)
    update_snapshot_status(snapshot_id, "ERROR")

    stable_snapshot = get_snapshot_by_status("STABLE")
    if not stable_snapshot:
        # Nothing proven to return to — a fresh deployment whose first task
        # failed. Raising here only turned one failed task into a dead
        # supervisor; restarting the agent is all that is left to do.
        logger.warning("No stable snapshot to roll back to, restarting agent as is")
        start_agent()
        return {"rolled_back": False, "error_text": error_text}

    _, snapshot_sha, _ = stable_snapshot
    logger.info("Agent broke its own source, rolling back to %s", snapshot_sha[:8])
    git_service.rollback(snapshot_sha)
    start_agent()

    return {"rolled_back": True, "error_text": error_text}


def ack_handler(git_service: GitService):
    mark_pending_snapshot_stable()

    # The task went through on this code, so anything still uncommitted is
    # proven too and belongs in the stable history.
    git_service.check(is_stable=True)


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

    elif isinstance(command, GetStableCommitsCommand):
        result = git_service.log()

    return {"stdout": result}


def client_data_handler(message: dict) -> dict:
    action = message["action"]

    if action == "list_chats":
        return {"chats": list_chats()}

    if action == "create_chat":
        return {"chat": create_chat(str(message["title"]))}

    if action == "rename_chat":
        return {"chat": rename_chat(int(message["chat_id"]), str(message["title"]))}

    if action == "get_history":
        return {"messages": get_chat_history(int(message["chat_id"]))}

    if action == "list_models":
        # An unreachable model is an ordinary answer, not a failure of the
        # request: the client shows it next to the model picker and carries on.
        try:
            return {
                "models": list_models(
                    str(message.get("provider") or ""),
                    str(message.get("url") or ""),
                )
            }
        except Exception as error:
            logger.warning("Model list unavailable: %s", error)
            return {"error": f"Модель недоступна по этому адресу: {_short_reason(error)}"}

    if action == "add_client_message":
        return {
            "id": add_client_message(
                int(message["chat_id"]),
                str(message["message_type"]),
                message["message"],
            )
        }

    raise ValueError(f"Unknown client data action: {action}")
