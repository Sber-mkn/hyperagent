"""Shared helpers for reading the on-disk skill catalog."""

from __future__ import annotations


def skill_description(content: str) -> str:
    """First non-header, non-blank line of a skill .md file -- the one-line
    summary shown in the catalog (skills_list) and used when deciding
    whether a newly proposed skill duplicates an existing one."""
    for line in content.splitlines()[1:]:
        line = line.strip()
        if line and not line.startswith("#"):
            return line
    return ""
