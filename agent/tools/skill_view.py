"""Read one learned skill by name."""

from __future__ import annotations

import re

from agent.tools.registry import tool, truncate_middle


MAX_SKILL_CHARS = 20_000
_SKILL_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


@tool
def skill_view(name: str) -> str:
    """Load the complete instructions for one learned skill.

    Args:
        name: Exact skill name returned by skills_list.
    """
    from agent.config import DATA_DIR

    if not _SKILL_NAME.fullmatch(name):
        return f"[invalid skill name: {name}]"

    path = DATA_DIR / "skills" / f"{name}.md"
    if not path.is_file():
        return f"[skill not found: {name}]"

    return truncate_middle(path.read_text(encoding="utf-8"), MAX_SKILL_CHARS)
