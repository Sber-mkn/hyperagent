import importlib
import logging
import pkgutil

from agent.tools.registry import (
    Tool, tool, get_tool, all_tools, tools_spec, run_tool_calls, truncate_middle,
    execute_tool, tool_target,
)
from agent.tools import builtin

logger = logging.getLogger(__name__)

# Auto-load every tool module in this package (one @tool per file) so new
# tool modules become available without hand-editing this file. A broken
# module (e.g. missing `from agent.tools.registry import tool`) must not
# take down every other tool with it, so failures are logged and skipped.
for _module_info in pkgutil.iter_modules(__path__):
    if _module_info.name not in ("registry", "builtin"):
        try:
            importlib.import_module(f"{__name__}.{_module_info.name}")
        except Exception:
            logger.exception("Failed to load tool module %s", _module_info.name)
del _module_info

__all__ = [
    "Tool", "tool", "get_tool", "all_tools", "tools_spec", "run_tool_calls", "truncate_middle",
    "execute_tool", "tool_target",
]
