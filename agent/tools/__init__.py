from agent.tools.registry import (
    Tool, tool, get_tool, all_tools, tools_spec, run_tool_calls,
)
from agent.tools import builtin   # noqa: F401  -- импорт регистрирует встроенные инструменты

__all__ = ["Tool", "tool", "get_tool", "all_tools", "tools_spec", "run_tool_calls"]
