"""File and shell tools for the V3 agent."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from agent.config import AGENT_ROOT
from agent.session_events import current
from agent.tools.paths import resolve_write_path
from agent.tools.registry import tool


def _record_write(path: Path) -> None:
    sess = current()
    if not sess:
        return
    resolved = path.resolve().as_posix()
    sess.record_artifact(resolved)
    agent_root = AGENT_ROOT.resolve().as_posix()
    if resolved == agent_root or resolved.startswith(agent_root + "/"):
        sess.record_agent_file(resolved)


@tool
def read_file(path: str) -> str:
    """Read and return the full text contents of a file at the given path."""
    p = Path(path)
    if not p.exists():
        return f"ERROR: file does not exist: {path}"
    return p.read_text(encoding="utf-8")


@tool
def write_file(path: str, content: str) -> str:
    """Create or overwrite a file with the full new content."""
    try:
        p = resolve_write_path(path)
    except PermissionError as exc:
        return f"ERROR: {exc}"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    _record_write(p)
    return f"WROTE {path} ({len(content)} chars)"


@tool
def list_files(directory: str) -> str:
    """List all files recursively in a directory."""
    base = Path(directory)
    if not base.exists():
        return f"ERROR: directory does not exist: {directory}"
    files = [str(p) for p in base.rglob("*") if p.is_file() and ".git" not in p.parts]
    return "\n".join(files) if files else "(empty)"


@tool
def run_bash(command: str, cwd: str = ".") -> str:
    """Run a shell command in the given working directory."""
    try:
        r = subprocess.run(
            command,
            shell=True,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=120,
        )
        return f"EXIT={r.returncode}\nSTDOUT:\n{r.stdout}\nSTDERR:\n{r.stderr}"
    except subprocess.TimeoutExpired:
        return "ERROR: command timed out after 120s"


@tool
def run_python(file_path: str, cwd: str = ".") -> str:
    """Run a Python file and return its output."""
    return run_bash(f'"{sys.executable}" "{file_path}"', cwd=cwd)
