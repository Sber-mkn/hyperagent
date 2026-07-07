"""Write-path guards: agent may write only under agent/ and workdir/."""

from __future__ import annotations

from pathlib import Path

from agent.config import AGENT_ROOT, AGENT_WORKDIR, CONSTITUTION_DIR

FORBIDDEN_PREFIXES = [
    CONSTITUTION_DIR.resolve(),
    Path("/hyperagent/agent_immutable"),
    Path("/hyperagent/supervisor"),
]


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return path.resolve() == root.resolve()


def _rewrite_docker_path(path: str) -> Path:
    """Map /hyperagent/... paths to local dirs when running outside Docker."""
    normalized = path.replace("\\", "/")
    if normalized.startswith("/hyperagent/workdir"):
        rel = normalized.removeprefix("/hyperagent/workdir").lstrip("/")
        return (AGENT_WORKDIR / rel) if rel else AGENT_WORKDIR
    if normalized.startswith("/hyperagent/agent"):
        rel = normalized.removeprefix("/hyperagent/agent").lstrip("/")
        return (AGENT_ROOT / rel) if rel else AGENT_ROOT
    return Path(path)


def resolve_write_path(path: str) -> Path:
    p = _rewrite_docker_path(path).resolve()
    for forbidden in FORBIDDEN_PREFIXES:
        if forbidden.exists() and _is_under(p, forbidden.resolve()):
            raise PermissionError(f"Writes forbidden: {path}")
    agent_root = AGENT_ROOT.resolve()
    work_root = AGENT_WORKDIR.resolve()
    if _is_under(p, agent_root) or _is_under(p, work_root):
        return p
    raise PermissionError(
        f"Writes only allowed under {agent_root.as_posix()}/ or {work_root.as_posix()}/: {path}"
    )
