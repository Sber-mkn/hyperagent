"""Mutable agent entry — called by agent_immutable/main.py."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from agent.agent_loop import AgentResult, ReactAgent
from agent.clients import build_client, default_model
from agent.config import AGENT_WORKDIR, DATA_DIR, SUMMARIZER_MODEL
from agent.memory.store import MemoryStore
from agent.session_events import SessionEvents, activate, deactivate

logger = logging.getLogger(__name__)


@dataclass
class SessionReport:
    """Structured session result — serialized to JSON for client and supervisor."""

    client_status: str = "success"
    client_answer: str = ""
    client_artifacts: list[str] = field(default_factory=list)
    supervisor_commits: list[dict] = field(default_factory=list)
    supervisor_files_changed: list[str] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)

    def to_json(self) -> str:
        self_mod = bool(self.supervisor_commits)
        notes = (
            f"Registered {len(self.supervisor_commits)} self-mod commit(s)"
            if self_mod
            else "No self-mod commits this session"
        )
        if self.supervisor_files_changed and not self_mod:
            notes += f"; edited agent files: {', '.join(self.supervisor_files_changed)}"

        return json.dumps(
            {
                "client": {
                    "status": self.client_status,
                    "summary": self._summary(),
                    "answer": self.client_answer,
                    "artifacts": self.client_artifacts,
                },
                "supervisor": {
                    "self_mod_performed": self_mod,
                    "commits": self.supervisor_commits,
                    "files_changed": self.supervisor_files_changed,
                    "notes": notes,
                },
                "metrics": self.metrics,
            },
            ensure_ascii=False,
            indent=2,
        )

    def _summary(self) -> str:
        text = (self.client_answer or "").strip()
        return text[:500] if text else "(no answer)"


def _docker_task_prefix() -> str:
    workdir = AGENT_WORKDIR.as_posix()
    return (
        "Environment: Docker/Linux.\n"
        f"- Save user task files under {workdir}/ (example: {workdir}/hello.py).\n"
        "- You MUST use tools (write_file, run_python, run_bash) for coding tasks. "
        "Do not answer with code in plain text only.\n"
        "- When the task is done, reply with a short plain-text summary.\n\n"
        "Task:\n"
    )


def _build_prompt(
    task: str,
    error_text: str | None,
    snapshot_text: str | None,
) -> str:
    """Merge user task with rollback context when supervisor sends error info."""
    task = (task or "").strip()
    if not error_text:
        return _docker_task_prefix() + task

    return (
        "IMPORTANT: The previous version of your code failed after a self-modification. "
        "You were rolled back to the last stable version.\n\n"
        f"--- Error traceback ---\n{error_text.strip()}\n\n"
        f"--- Failed change description ---\n{(snapshot_text or '(no description)').strip()}\n\n"
        "--- Current task ---\n"
        + _docker_task_prefix()
        + task
    )


def _metrics_from_result(result: AgentResult) -> dict:
    return {
        "iterations": result.iterations,
        "tool_calls": result.tool_calls,
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
        "total_tokens": result.input_tokens + result.output_tokens,
        "elapsed_s": round(result.elapsed_s, 2),
        "compressions": result.compressions,
    }


def agent_logic(
    task: str = "",
    error_text: str | None = None,
    snapshot_text: str | None = None,
) -> str:
    """
    Run one agent session. Returns JSON string (client + supervisor + metrics).

    Called by agent_immutable after RabbitMQ delivers a task.
    Raise on failure so the immutable shell sends error to supervisor.
    """
    events = SessionEvents()
    activate(events)
    try:
        MemoryStore.reset(DATA_DIR)
        AGENT_WORKDIR.mkdir(parents=True, exist_ok=True)

        prompt = _build_prompt(task, error_text, snapshot_text)
        logger.info("agent_logic start (prompt chars=%d)", len(prompt))

        llm_client = build_client()
        agent = ReactAgent(
            client=llm_client,
            agent_model=default_model(),
            summarizer_model=SUMMARIZER_MODEL,
            verbose=True,
        )
        result = agent.run(prompt)

        report = SessionReport(
            client_status="success" if result.tool_calls > 0 else "incomplete",
            client_answer=result.answer,
            client_artifacts=list(events.artifacts),
            supervisor_commits=list(events.commits),
            supervisor_files_changed=list(events.files_changed),
            metrics=_metrics_from_result(result),
        )
        payload = report.to_json()
        logger.info(
            "agent_logic done steps=%d tools=%d tokens=%d",
            result.iterations,
            result.tool_calls,
            result.input_tokens + result.output_tokens,
        )
        return payload
    finally:
        deactivate()
