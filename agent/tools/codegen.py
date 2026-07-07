"""Meta-tools: generate user code and register new agent capabilities."""

from __future__ import annotations

import ast
import importlib.util
import re
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from agent.config import MAX_OUTPUT_TOKENS
from agent.llminterface.client.llm_chat import LLMChat
from agent.session_events import current
from agent.tools.paths import generated_tool_dir, resolve_workdir_path
from agent.tools.registry import has_tool, tool

if TYPE_CHECKING:
    from agent.llminterface.client.llm_client import LLMClient

_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_RESERVED = frozenset(
    {
        "read_file",
        "write_file",
        "list_files",
        "run_bash",
        "run_python",
        "generate_code",
        "create_tool",
    }
)
_client: LLMClient | None = None
_model: str | None = None


def activate_codegen(client: LLMClient, model: str) -> None:
    """Make the current session's model available to generate_code."""
    global _client, _model
    _client, _model = client, model


def deactivate_codegen() -> None:
    global _client, _model
    _client, _model = None, None


def _record_artifact(path: Path) -> None:
    sess = current()
    if sess:
        sess.record_artifact(path.resolve().as_posix())


def _validate_tool_name(name: str) -> str | None:
    if not _NAME_RE.match(name):
        return "name must be snake_case (letters, digits, underscore)"
    if name in _RESERVED:
        return f"name {name!r} is reserved"
    if has_tool(name):
        return f"tool {name!r} already exists"
    return None


def _normalize_function_source(code: str) -> str:
    """Accept accidental @tool wrappers, but store one plain function."""
    lines = code.strip().splitlines()
    while lines and lines[0].strip().startswith("@tool"):
        lines = lines[1:]
    return "\n".join(lines).strip()


def _validate_function_source(name: str, code: str) -> str | None:
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return f"invalid Python: {exc}"
    if len(tree.body) != 1 or not isinstance(tree.body[0], ast.FunctionDef):
        return "code must contain exactly one top-level function definition"
    func = tree.body[0]
    if func.name != name:
        return f"function must be named {name!r}, got {func.name!r}"
    if func.decorator_list:
        return "do not include decorators; create_tool adds @tool"
    return None


def _module_source(name: str, description: str, code: str) -> str:
    desc = description.strip() or f"Generated tool {name}"
    return (
        f'"""Auto-generated tool: {name}"""\n'
        "from __future__ import annotations\n\n"
        "from agent.tools.registry import tool\n\n"
        f"@tool(name={name!r}, description={desc!r})\n"
        f"{code.strip()}\n"
    )


def _load_generated(path: Path, module_name: str) -> str | None:
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        return f"failed to load module spec for {path}"
    module = importlib.util.module_from_spec(spec)
    try:
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
    except Exception as exc:
        sys.modules.pop(module_name, None)
        return f"failed to import generated tool: {exc}"
    tool_name = module_name.rsplit(".", 1)[-1]
    if not has_tool(tool_name):
        return "tool was written but did not register; check @tool decorator"
    return None


def load_generated_tools() -> list[str]:
    """Register persisted generated tools on agent startup."""
    gen_dir = generated_tool_dir()
    if not gen_dir.exists():
        return []

    loaded: list[str] = []
    for path in sorted(gen_dir.glob("*.py")):
        name = path.stem
        if path.name.startswith("_") or not _NAME_RE.match(name) or has_tool(name):
            continue
        err = _load_generated(path, f"agent.tools.generated.{name}")
        if err is None:
            loaded.append(name)
    return loaded


def _strip_outer_fence(text: str) -> str:
    text = (text or "").strip()
    match = re.fullmatch(r"```(?:\w+)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    return match.group(1).strip() if match else text


def _generate_source(path: str, instruction: str, context: str = "") -> str:
    if _client is None or _model is None:
        return "ERROR: code generation runtime is not active"

    prompt = (
        "Write the complete source code for the requested user deliverable.\n"
        f"Target path: {path}\n\n"
        f"Instruction:\n{instruction.strip()}"
    )
    if context.strip():
        prompt += f"\n\nAdditional context:\n{context.strip()}"

    chat = LLMChat(
        [
            {
                "role": "system",
                "content": (
                    "You are a focused code generator. Output only raw source code. "
                    "Do not include markdown fences, explanations, XML, or tool calls."
                ),
            },
            {"role": "user", "content": prompt},
        ]
    )
    reply = _client.send(
        chat,
        model=_model,
        temperature=0,
        max_tokens=MAX_OUTPUT_TOKENS,
    )
    return _strip_outer_fence(reply[-1].content or "")


@tool
def generate_code(path: str, instruction: str, context: str = "") -> str:
    """Generate a user deliverable file and save it under workdir/.

    Use for scripts and task output the user asked for.
    Do NOT use for agent self-mod (use write_file on /hyperagent/agent/) or for
    new agent tools (use create_tool).
    """
    try:
        target = resolve_workdir_path(path)
    except PermissionError as exc:
        return f"ERROR: {exc}"

    code = _generate_source(path, instruction, context)
    if code.startswith("ERROR:"):
        return code
    if not code.strip():
        return "ERROR: code generator returned empty output"

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(code, encoding="utf-8")
    _record_artifact(target)
    return f"GENERATED {path} ({len(code)} chars)"


@tool
def create_tool(name: str, description: str, code: str) -> str:
    """Register a new agent tool when no built-in tool can do the job.

    Write the tool first, then call it in a later step.

    name: snake_case tool name (e.g. count_lines).
    description: one-line summary shown to the model.
    code: a single Python function definition, e.g.:

        def count_lines(path: str) -> str:
            \"\"\"Count lines in a text file.\"\"\"
            return str(len(open(path, encoding='utf-8').readlines()))

    The function is saved under agent/tools/generated/, imported, and registered
    for the rest of this session.
    """
    err = _validate_tool_name(name)
    if err:
        return f"ERROR: {err}"

    code = _normalize_function_source(code)
    err = _validate_function_source(name, code)
    if err:
        return f"ERROR: {err}"

    gen_dir = generated_tool_dir()
    gen_dir.mkdir(parents=True, exist_ok=True)
    path = gen_dir / f"{name}.py"
    if path.exists():
        return f"ERROR: generated tool file already exists: {path}"

    source = _module_source(name, description, code)
    path.write_text(source, encoding="utf-8")

    module_name = f"agent.tools.generated.{name}"
    err = _load_generated(path, module_name)
    if err:
        path.unlink(missing_ok=True)
        return f"ERROR: {err}"

    sess = current()
    if sess:
        sess.record_agent_file(path.resolve().as_posix())

    return f"CREATED TOOL {name!r}; available now via tool_calls (total tools: {len(_tool_names())})"


def _tool_names() -> list[str]:
    from agent.tools.registry import tool_names

    return tool_names()
