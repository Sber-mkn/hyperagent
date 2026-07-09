"""Mutable agent entry called by agent_immutable/main.py.

This file intentionally contains a lightweight simulation of the real agent loop.
It exercises the callback surface used by the immutable runner and supervisor.
"""

from __future__ import annotations

import json
import logging
import os
import pathlib
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

AGENT_WORKDIR = pathlib.Path(os.getenv("AGENT_WORKDIR", "/hyperagent/agent/workdir"))


@dataclass
class SessionReport:
    client_status: str = "success"
    client_answer: str = ""
    client_artifacts: list[str] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)

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


def _end_message(content: str) -> dict:
    return {
        "done": True,
        "role": "assistant",
        "thinking": "",
        "content": content,
        "provider": "simulation",
        "model": "simulation",
    }


def _write_hello_file() -> pathlib.Path:
    AGENT_WORKDIR.mkdir(parents=True, exist_ok=True)
    hello_file = AGENT_WORKDIR / "hello.py"
    hello_file.write_text('print("Привет!")\n', encoding="utf-8")
    return hello_file


def agent_logic(
    on_command,
    on_content,
    on_end_message,
    on_think,
    task: str = "",
    error_text: str | None = None,
    llm_chat: list[dict] | None = None,
) -> str:
    logger.info(
        "simulation agent start task=%r error=%s llm_chat=%d",
        task,
        bool(error_text),
        len(llm_chat or []),
    )

    on_think("Симуляция: получил задачу и начинаю проверять callbacks.")
    on_content(f"Task: {task or '(empty)'}")

    if error_text:
        on_content(f"Получил error_text после rollback: {error_text[:500]}")
        on_end_message(_end_message("Симуляция завершила recovery после ошибки."))
        return SessionReport(
            client_status="success",
            client_answer="Recovered after simulated rollback.",
            metrics={"mode": "recovery", "llm_chat_messages": len(llm_chat or [])},
        ).to_json()

    if llm_chat:
        on_think("Симуляция: это запуск после self-mod commit, сейчас проверю error flow.")
        on_end_message(_end_message("Симулирую падение после перезапуска агента."))
        raise RuntimeError("Simulated agent failure after committed restart")

    client_result = on_command({"type": "client_command", "command": "echo client-command-ok"})
    on_content(f"client_command response: {client_result}")

    status_before = on_command({"type": "git", "command": {"command": "status"}})
    on_content(f"git status before change: {status_before}")

    hello_file = _write_hello_file()
    on_content(f"Создал файл: {hello_file.as_posix()}")

    diff_result = on_command({"type": "git", "command": {"command": "diff"}})
    on_content(f"git diff response: {diff_result}")

    on_end_message(_end_message("Сейчас инициирую self-mod commit."))
    commit_result = on_command(
        {
            "type": "git",
            "command": {
                "command": "commit",
                "message": "Simulation: add hello file",
            },
        }
    )
    on_content(f"git commit response: {commit_result}")

    raise RuntimeError("Simulated failure after commit command returned")
