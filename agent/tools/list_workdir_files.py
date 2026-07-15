"""Tool to list files in the workdir with optional filtering."""
import os
from typing import Optional
from agent.tools.registry import tool

@tool
def list_workdir_files(name_substring: Optional[str] = None) -> str:
    """
    List files in the workdir with optional name filtering.

    Args:
        name_substring: Optional substring to filter filenames (case insensitive)
    """
    workdir_path = "/hyperagent/workdir"

    if not os.path.exists(workdir_path):
        return "(empty)"

    files = os.listdir(workdir_path)

    if name_substring:
        name_substring = name_substring.lower()
        files = [f for f in files if name_substring in f.lower()]

    files = sorted(files)
    return "\n".join(files) if files else "(empty)"