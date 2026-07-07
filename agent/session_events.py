"""Per-session facts collected during agent_logic (artifacts, self-mod commits)."""

from __future__ import annotations

from dataclasses import dataclass, field

_current: SessionEvents | None = None


@dataclass
class SessionEvents:
    """Filled by tools during one agent_logic run."""

    artifacts: list[str] = field(default_factory=list)
    commits: list[dict] = field(default_factory=list)
    files_changed: list[str] = field(default_factory=list)

    def record_artifact(self, path: str) -> None:
        if path not in self.artifacts:
            self.artifacts.append(path)

    def record_agent_file(self, path: str) -> None:
        if path not in self.files_changed:
            self.files_changed.append(path)

    def record_commit(self, description: str, files: list[str], smoke_test: str = "ok") -> None:
        self.commits.append(
            {
                "description": description,
                "files": list(files),
                "smoke_test": smoke_test,
            }
        )


def activate(events: SessionEvents) -> None:
    global _current
    _current = events


def deactivate() -> None:
    global _current
    _current = None


def current() -> SessionEvents | None:
    return _current
