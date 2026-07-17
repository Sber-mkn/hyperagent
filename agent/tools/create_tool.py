"""Create, validate, and load persistent generated tools."""

from __future__ import annotations

import ast
import importlib.util
import logging
import re
import sys
from pathlib import Path

from agent.tools.registry import all_tools, tool

logger = logging.getLogger(__name__)
GENERATED_DIR = Path(__file__).with_name("generated")
TOOL_NAME = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


def _tool_decorator(node: ast.expr) -> bool:
    target = node.func if isinstance(node, ast.Call) else node
    return isinstance(target, ast.Name) and target.id == "tool"


def _validate(name: str, code: str) -> None:
    tree = ast.parse(code, filename=f"{name}.py")
    functions = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and any(_tool_decorator(item) for item in node.decorator_list)
    ]
    if len(functions) != 1:
        raise ValueError("code must define exactly one @tool function")

    entrypoint = functions[0]
    if isinstance(entrypoint, ast.AsyncFunctionDef):
        raise ValueError("generated tools must be synchronous functions")
    if entrypoint.name != name:
        raise ValueError(f"@tool function must be named {name!r}")
    if not ast.get_docstring(entrypoint):
        raise ValueError("generated tool function must have a docstring")

    imports_tool = any(
        isinstance(node, ast.ImportFrom)
        and node.module == "agent.tools.registry"
        and any(alias.name == "tool" for alias in node.names)
        for node in tree.body
    )
    if not imports_tool:
        raise ValueError("code must import tool from agent.tools.registry")
    if tree.body[-1] is not entrypoint:
        raise ValueError("the @tool function must be the final module statement")

    compile(tree, f"{name}.py", "exec")


def _load(path: Path, name: str) -> None:
    module_name = f"agent.tools._generated_{name}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load generated tool {name!r}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise

    if name not in {item.name for item in all_tools()}:
        sys.modules.pop(module_name, None)
        raise ValueError(f"module did not register tool {name!r}")


@tool
def create_tool(name: str, code: str) -> str:
    """Create and immediately register a reusable Python tool.

    Use this not only when no existing tool fits, but also once you've written
    (or rewritten) working code for the same procedure more than once, or you
    can tell the current task's code will likely be reused later — e.g. a
    parameterized "build this kind of report" or "apply this kind of edit"
    helper. Promoting it once it works avoids re-generating the same
    multi-step script from scratch (and re-sending it in full every future
    call) each time a similar request comes in. This costs one agent restart
    now (to register the tool) in exchange for much smaller, cheaper calls
    later — wait until the approach is actually working, not while still
    debugging it, so you don't pay the restart repeatedly for something
    you're still fixing.

    The code must be a complete Python module that imports ``tool`` from
    ``agent.tools.registry`` and ends with exactly one synchronous,
    docstring-documented ``@tool`` function whose name matches ``name``.

    Args:
        name: Python tool name using lowercase letters, digits, and underscores.
        code: Complete Python source code for the generated tool module.
    """
    name = name.strip()
    if not TOOL_NAME.fullmatch(name):
        raise ValueError(
            "name must start with a lowercase letter and contain only "
            "lowercase letters, digits, and underscores"
        )
    if name in {item.name for item in all_tools()}:
        raise ValueError(f"tool {name!r} already exists")

    code = code.strip()
    if code.startswith("```") and code.endswith("```"):
        code = code.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    _validate(name, code)

    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    path = GENERATED_DIR / f"{name}.py"
    if path.exists():
        raise ValueError(f"generated tool file already exists: {path}")

    path.write_text(code + "\n", encoding="utf-8")
    try:
        _load(path, name)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return f"Created and registered tool {name!r} at {path.as_posix()}"


def _load_persisted() -> None:
    if not GENERATED_DIR.is_dir():
        return
    registered = {item.name for item in all_tools()}
    for path in sorted(GENERATED_DIR.glob("*.py")):
        if path.stem in registered:
            continue
        try:
            _validate(path.stem, path.read_text(encoding="utf-8"))
            _load(path, path.stem)
            registered.add(path.stem)
        except Exception:
            logger.exception("Failed to load generated tool %s", path.name)


_load_persisted()
