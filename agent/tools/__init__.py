import importlib
import logging
import pkgutil

from agent.tools.registry import (
    Tool,
    all_tools,
    execute_tool,
    get_tool,
    run_tool_calls,
    tool,
    tool_target,
    tools_spec,
    truncate_middle,
)

logger = logging.getLogger(__name__)
importlib.import_module(f"{__name__}.builtin")

# Auto-load every tool module in this package (one @tool per file) so new
# tool modules become available without hand-editing this file. A broken
# module (e.g. missing `from agent.tools.registry import tool`) must not
# take down every other tool with it, so failures are logged and skipped.
# builtin is loaded by this same loop: it holds many @tool functions rather
# than one, but it still only needs importing, and excluding it here left
# every builtin tool unregistered once its explicit import was dropped.
for _module_info in pkgutil.iter_modules(__path__):
    if _module_info.name != "registry":
        try:
            importlib.import_module(f"{__name__}.{_module_info.name}")
        except Exception:
            logger.exception("Failed to load tool module %s", _module_info.name)
del _module_info

__all__ = [
    "Tool",
    "all_tools",
    "execute_tool",
    "get_tool",
    "run_tool_calls",
    "tool",
    "tool_target",
    "tools_spec",
    "truncate_middle",
]
