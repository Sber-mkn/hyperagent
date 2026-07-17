"""Mutable simulation agent used by agent_immutable/main.py.

The implementation deliberately exercises the runtime callback surface instead
of acting like a real LLM agent. It is useful as an end-to-end smoke test for
client streaming, supervisor requests, restart after commit, and recovery.
"""

from __future__ import annotations

import json
import logging
import os
import pathlib
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

AGENT_ROOT = pathlib.Path(os.getenv("AGENT_ROOT", "/hyperagent/agent"))
RESTART_CHECKPOINT = "[simulation:restart-checkpoint]"


@dataclass
class SessionReport:
    client_status: str = "success"
    client_answer: str = ""
    client_artifacts: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(
            {
                "client": {
                    "status": self.client_status,
                    "summary": self.client_answer[:500] if self.client_answer else "(no answer)",
                    "answer": self.client_answer,
                    "artifacts": self.client_artifacts,
                },
                "metrics": self.metrics,
            },
            ensure_ascii=False,
            indent=2,
        )


@dataclass
class EndMessage:
    done: bool = True
    done_reason: str | None = None
    role: str = "assistant"
    thinking: str = ""
    content: str = ""
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_id: str | None = None
    name: str | None = None
    provider: str = "simulation"
    model: str = "simulation"
    tokens: Any | None = None
    duration: Any | None = None
    dt: datetime = field(default_factory=lambda: datetime.now(UTC))


def _end_message(content: str, *, thinking: str = "", model: str = "simulation") -> EndMessage:
    return EndMessage(content=content, thinking=thinking, model=model)


def _write_probe_file(task: str) -> pathlib.Path:
    AGENT_ROOT.mkdir(parents=True, exist_ok=True)
    probe_file = AGENT_ROOT / "simulation_probe.json"
    payload = {
        "task": task,
        "updated_at": datetime.now(UTC).isoformat(),
        "purpose": "exercise git diff and commit requests",
    }
    probe_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return probe_file


def _title_from_task(task: str) -> str:
    normalized = " ".join(task.split())
    if not normalized:
        return "Simulation smoke test"
    return normalized[:48]


def _latest_message_content(llm_chat: list[dict] | None) -> str:
    if not llm_chat:
        return ""
    latest = llm_chat[0]
    return str(latest.get("content") or "")


def _is_restart_probe_run(llm_chat: list[dict] | None) -> bool:
    return RESTART_CHECKPOINT in _latest_message_content(llm_chat)


def _safe_preview(value: Any, limit: int = 700) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    if len(text) <= limit:
        return text
    return f"{text[:limit]}..."


def _git_request(command: dict[str, Any]) -> dict[str, Any]:
    return {"type": "git", "command": command}


def _emit_think(on_think: Callable[[str], Any], message: str) -> None:
    on_think(message)


def agent_logic(
    on_command: Callable[[dict[str, Any]], Any] | None = None,
    on_content: Callable[[str], Any] | None = None,
    on_end_message: Callable[[Any], Any] | None = None,
    on_think: Callable[[str], Any] | None = None,
    task: str = "",
    error_text: str | None = None,
    llm_chat: list[dict] | None = None,
    *,
    user_message: str | None = None,
    on_title: Callable[[str], Any] | None = None,
    on_tool: Callable[[dict[str, Any]], Any] | None = None,
    on_tool_call: Callable[[str, Any, str, str], Any] | None = None,
    on_error: Callable[[str], Any] | None = None,
    on_start_message: Callable[[str], Any] | None = None,
    on_l3: Callable[[dict[str, Any]], Any] | None = None,
    agent_session: dict[str, Any] | None = None,
    l3_memory: dict[str, Any] | None = None,
    agent_type: str | None = None,
    agent_config: dict[str, Any] | None = None,
) -> str:
    if user_message is not None:
        task = user_message
    task = task or ""
    if on_tool is not None:
        on_command = on_tool

    raw_agent_session = agent_session or {}
    agent_type = agent_type or raw_agent_session.get("agent_type") or "local"
    agent_config = agent_config or raw_agent_session.get("agent_config") or {}
    model = str(agent_config.get("AGENT_MODEL") or "simulation")

    required_callbacks = {
        "on_command/on_tool": on_command,
        "on_content": on_content,
        "on_end_message": on_end_message,
        "on_think": on_think,
    }
    missing = [name for name, callback in required_callbacks.items() if callback is None]
    if missing:
        raise ValueError(f"agent_logic missing required callbacks: {', '.join(missing)}")

    logger.info(
        "simulation agent start task=%r error=%s llm_chat=%d agent_type=%r model=%r",
        task,
        bool(error_text),
        len(llm_chat or []),
        agent_type,
        model,
    )

    if error_text:
        return _run_recovery_scenario(
            error_text=error_text,
            model=model,
            llm_chat=llm_chat,
            l3_memory=l3_memory,
            on_content=on_content,
            on_end_message=on_end_message,
            on_l3=on_l3,
            on_start_message=on_start_message,
            on_think=on_think,
            on_title=on_title,
            task=task,
        )

    if _is_restart_probe_run(llm_chat):
        return _run_restart_scenario(
            model=model,
            on_content=on_content,
            on_end_message=on_end_message,
            on_start_message=on_start_message,
            on_think=on_think,
            on_tool_call=on_tool_call,
            task=task,
        )

    return _run_full_smoke_scenario(
        agent_type=agent_type,
        model=model,
        on_command=on_command,
        on_content=on_content,
        on_end_message=on_end_message,
        on_l3=on_l3,
        on_start_message=on_start_message,
        on_think=on_think,
        on_title=on_title,
        on_tool_call=on_tool_call,
        task=task,
    )


def _run_recovery_scenario(
    *,
    error_text: str,
    model: str,
    llm_chat: list[dict] | None,
    l3_memory: dict[str, Any] | None,
    on_content: Callable[[str], Any],
    on_end_message: Callable[[Any], Any],
    on_l3: Callable[[dict[str, Any]], Any] | None,
    on_start_message: Callable[[str], Any] | None,
    on_think: Callable[[str], Any],
    on_title: Callable[[str], Any] | None,
    task: str,
) -> str:
    if on_title is not None:
        on_title(_title_from_task(task))
    if on_start_message is not None:
        on_start_message(f"{model} - recovery")

    _emit_think(on_think, "Checking recovery after supervisor rollback.")
    on_content("Supervisor rolled back the failed pending snapshot and restarted the agent.")
    on_content(f"\nError preview: {error_text[:500]}")

    last_message_id = on_end_message(
        _end_message(
            "Recovery smoke scenario completed.",
            thinking="rollback and recovery path verified",
            model=model,
        )
    )
    if on_l3 is not None:
        on_l3(
            {
                "summary": "Simulation recovery path completed.",
                "last_message_id": last_message_id,
            }
        )

    return SessionReport(
        client_answer="Recovered after simulated restart failure.",
        metrics={
            "mode": "recovery",
            "llm_chat_messages": len(llm_chat or []),
            "had_l3_memory": l3_memory is not None,
        },
    ).to_json()


def _run_restart_scenario(
    *,
    model: str,
    on_content: Callable[[str], Any],
    on_end_message: Callable[[Any], Any],
    on_start_message: Callable[[str], Any] | None,
    on_think: Callable[[str], Any],
    on_tool_call: Callable[[str, Any, str, str], Any] | None,
    task: str,
) -> str:
    if on_start_message is not None:
        on_start_message(f"{model} - restarted")

    _emit_think(on_think, "Agent restarted after commit. Checking the error flow now.")
    if task:
        on_content("The original task was preserved across restart.")
    else:
        on_content("Restart arrived without a user task.")

    if on_tool_call is not None:
        on_tool_call(
            "simulation_error_probe",
            {"reason": "verify supervisor rollback and recovery"},
            "agent",
            "raising RuntimeError",
        )

    on_end_message(
        _end_message(
            "Restart smoke scenario reached intentional failure.",
            thinking="intentional failure after restart",
            model=model,
        )
    )
    raise RuntimeError("Simulated failure after committed restart")


def _run_full_smoke_scenario(
    *,
    agent_type: str,
    model: str,
    on_command: Callable[[dict[str, Any]], Any],
    on_content: Callable[[str], Any],
    on_end_message: Callable[[Any], Any],
    on_l3: Callable[[dict[str, Any]], Any] | None,
    on_start_message: Callable[[str], Any] | None,
    on_think: Callable[[str], Any],
    on_title: Callable[[str], Any] | None,
    on_tool_call: Callable[[str, Any, str, str], Any] | None,
    task: str,
) -> str:
    if on_title is not None:
        on_title(_title_from_task(task))
    if on_start_message is not None:
        on_start_message(model)

    _emit_think(on_think, "Checking the streaming think block.")
    _emit_think(
        on_think,
        "\nChecking client_command, git status, git diff, git log, and commit/restart.",
    )
    on_content("Smoke-run started. Checking safe callback and request scenarios.")

    unknown_result = on_command({"type": "unknown"})
    on_content(f"\nunknown command response: {_safe_preview(unknown_result)}")

    if on_tool_call is not None:
        on_tool_call("client_command", {"command": "echo client-command-ok"}, "client", "pending")
    client_result = on_command({"type": "client_command", "command": "echo client-command-ok"})
    on_content(f"\nclient_command response: {_safe_preview(client_result)}")

    status_before = on_command(_git_request({"command": "status"}))
    on_content(f"\ngit status response: {_safe_preview(status_before)}")

    log_result = on_command(_git_request({"command": "log"}))
    on_content(f"\ngit log response: {_safe_preview(log_result)}")

    stable_hash = _first_snapshot_hash(log_result)
    if stable_hash is not None:
        diff_hash_result = on_command(_git_request({"command": "diff", "hash": stable_hash}))
        on_content(f"\ngit diff(hash) response: {_safe_preview(diff_hash_result)}")

    probe_file = _write_probe_file(task)
    if on_tool_call is not None:
        on_tool_call(
            "write_file",
            {"path": probe_file.as_posix()},
            "agent",
            "simulation probe updated",
        )
    on_content(f"\nUpdated smoke file: {probe_file.as_posix()}")

    diff_result = on_command(_git_request({"command": "diff"}))
    on_content(f"\ngit diff response: {_safe_preview(diff_result)}")

    if on_start_message is not None:
        on_start_message(f"{model} - validation")
    on_content("\nThe model phase changed, so a second start event was sent.")

    last_message_id = on_end_message(
        _end_message(
            f"{RESTART_CHECKPOINT} Commit smoke scenario reached restart checkpoint.",
            thinking="all pre-commit callbacks and safe requests verified",
            model=model,
        )
    )
    if on_l3 is not None:
        on_l3(
            {
                "summary": "Simulation smoke run reached commit/restart checkpoint.",
                "last_message_id": last_message_id,
            }
        )

    if on_tool_call is not None:
        on_tool_call(
            "git_commit",
            {"message": "Simulation: exercise all agent callbacks"},
            "supervisor",
            "restart expected",
        )

    on_content("\nSending git commit. If there are changes, supervisor will restart the agent.")
    commit_result = on_command(
        _git_request({"command": "commit", "message": "Simulation: exercise all agent callbacks"})
    )
    on_content(f"\ngit commit response: {_safe_preview(commit_result)}")

    return SessionReport(
        client_answer="Smoke scenario completed without restart.",
        client_artifacts=[probe_file.as_posix()],
        metrics={"mode": "full", "agent_type": agent_type, "model": model},
    ).to_json()


def _first_snapshot_hash(log_result: Any) -> str | None:
    if not isinstance(log_result, dict):
        return None
    stdout = log_result.get("stdout")
    if not isinstance(stdout, dict):
        return None
    for snapshot_hash in stdout:
        if isinstance(snapshot_hash, str) and 7 <= len(snapshot_hash) <= 40:
            return snapshot_hash
    return None
