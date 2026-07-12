"""List learned skills available to the agent."""

from __future__ import annotations

import json

from agent.config import DATA_DIR
from agent.tools.registry import tool


@tool
def skills_list() -> str:
    """List learned skills with descriptions so a relevant one can be selected."""
    skills_dir = DATA_DIR / "skills"
    catalog: list[dict[str, str]] = []

    if skills_dir.is_dir():
        for path in sorted(skills_dir.glob("*.md")):
            content = path.read_text(encoding="utf-8")
            catalog.append(
                {
                    "name": path.stem,
                    "description": _description(content),
                }
            )

    return json.dumps(catalog, ensure_ascii=False)


def _description(content: str) -> str:
    for line in content.splitlines()[1:]:
        line = line.strip()
        if line and not line.startswith("#"):
            return line
    return ""
