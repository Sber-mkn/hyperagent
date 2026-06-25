"""Tools the agent can use.

Each tool is a plain Python function decorated with @tool.
IMPORTANT: the docstring (the \"\"\"...\"\"\" right under def) is NOT a comment for humans —
LangChain sends it to the LLM as the tool's description. The model reads it to decide
WHEN to call the tool. If you delete the docstring, @tool raises an error.

The agent (orchestrator) never touches files directly. It only emits a tool call like
  write_file(path="x.py", content="def add(a,b): return a+b")
and THIS code executes it. That is the safety boundary.
"""

import subprocess
import sys
import json
import textwrap
from pathlib import Path

from langchain_core.tools import tool
from langchain_core.messages import HumanMessage, SystemMessage

from llm import coder_llm

# Where generated tools get written (the agent extending itself)
GENERATED_TOOLS_DIR = Path(__file__).parent / "generated_tools"

_CODER_SYSTEM = (
    "You are deepseek-coder. Return strict JSON only, no markdown fences."
)

_CODER_FORMAT = {
    "type": "object",
    "properties": {
        "realizable": {"type": "boolean"},
        "reason": {"type": "string"},
        "code": {"type": "string"},
    },
    "required": ["realizable", "reason", "code"],
}


def _build_coder_prompt(
    description: str,
    language: str = "",
    signature: str = "",
    requirements: str = "",
    examples: str = "",
) -> str:
    return textwrap.dedent(
        f"""
        TASK DESCRIPTION:
        {description or "(empty)"}

        LANGUAGE:
        {language or "Python"}

        SIGNATURE / TARGET INTERFACE:
        {signature or "(not specified)"}

        REQUIREMENTS:
        {requirements or "(none)"}

        EXAMPLES:
        {examples or "(none)"}

        Respond with JSON fields:
        - realizable: boolean
        - reason: short string
        - code: full self-contained code that can be executed
        """
    ).strip()


def _extract_json_object(raw) -> dict | None:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, list):
        # Some local models may return [{"type":"text","text":"..."}]
        joined = " ".join(str(x.get("text", x)) if isinstance(x, dict) else str(x) for x in raw)
        raw = joined

    text = raw.strip() if isinstance(raw, str) else str(raw or "").strip()
    if not text:
        return None
    # strip accidental code fences
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3:
            text = "\n".join(lines[1:-1]).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                return None
    return None


def _truncate(text: str, limit: int = 8000) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... [truncated, total {len(text)} chars]"


# ── File tools ──────────────────────────────────────────────────────────────
@tool
def get_weather(city: str) -> str:
    """Return weather for a city. Accepts English city names only."""
    ru_letters = "йцукенгшщзхъфывапролджэячсмитьбю"
    if city and city[0] in ru_letters + ru_letters.upper():
        raise ValueError("Function accepts English city names only")
    return f"In {city} it is +20C"


@tool
def get_city() -> str:
    """Auto-detect the user's city for weather requests."""
    return "Moscow"


@tool
def read_file(path: str) -> str:
    """Read and return the full text contents of a file at the given path.
    Use this before editing a file so you know its current content."""
    p = Path(path)
    if not p.exists():
        return f"ERROR: file does not exist: {path}"
    return p.read_text(encoding="utf-8")


@tool
def write_file(path: str, content: str) -> str:
    """Overwrite (or create) a file with the FULL new content. Never pass partial
    edits or diffs — always the complete file. Returns a confirmation string."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return f"WROTE {path} ({len(content)} chars)"


@tool
def list_files(directory: str) -> str:
    """List all files recursively in a directory. Returns newline-separated paths."""
    base = Path(directory)
    if not base.exists():
        return f"ERROR: directory does not exist: {directory}"
    files = [str(p) for p in base.rglob("*") if p.is_file() and ".git" not in p.parts]
    return "\n".join(files) if files else "(empty)"


# ── Shell / run tools ─────────────────────────────────────────────────────────
@tool
def run_bash(command: str, cwd: str = ".") -> str:
    """Run a shell command in the given working directory (compile, git, ls, etc.).
    Returns exit code + stdout + stderr. Use for compiling and running tests."""
    try:
        r = subprocess.run(
            command, shell=True, cwd=cwd,
            capture_output=True, text=True, timeout=120,
        )
        return f"EXIT={r.returncode}\nSTDOUT:\n{r.stdout}\nSTDERR:\n{r.stderr}"
    except subprocess.TimeoutExpired:
        return "ERROR: command timed out after 120s"


@tool
def run_python(file_path: str, cwd: str = ".") -> str:
    """Run a python file and return its output. Use to verify generated code works."""
    # sys.executable = the real interpreter (avoids Windows' Store-stub 'python')
    return run_bash.func(f'"{sys.executable}" "{file_path}"', cwd=cwd)


# ── Web / edit parity tools (same instrument set as no-framework agent) ───────
@tool
def web_search(query: str, num_results: int = 5) -> str:
    """Search the web with DuckDuckGo and return title/link/snippet lines."""
    try:
        from duckduckgo_search import DDGS
    except ImportError:
        return "ERROR: install duckduckgo-search to use web_search"

    out = []
    with DDGS() as ddgs:
        for r in ddgs.text(query, max_results=num_results):
            out.append(f"- {r['title']}\n  {r['href']}\n  {r['body']}")
    return "\n\n".join(out) if out else "No results."


@tool
def fetch_url(url: str) -> str:
    """Fetch URL text content (no JS rendering) and return cleaned page text."""
    try:
        import requests
        from bs4 import BeautifulSoup
    except ImportError:
        return "ERROR: install requests and beautifulsoup4"

    resp = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()
    return _truncate(soup.get_text(separator="\n", strip=True))


@tool
def fetch_url_render(url: str) -> str:
    """Fetch URL with JavaScript rendering via Playwright and return body text."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return "ERROR: install playwright and run `playwright install chromium`"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(url, wait_until="networkidle", timeout=30000)
        text = page.inner_text("body")
        browser.close()
    return _truncate(text)


@tool
def change_file(path: str, old: str, new: str, encoding: str = "utf-8") -> str:
    """Replace one exact text fragment in a file. The `old` fragment must be unique."""
    p = Path(path)
    if not p.exists():
        return f"ERROR: file does not exist: {path}"
    original = p.read_text(encoding=encoding)
    count = original.count(old)
    if count == 0:
        return "ERROR: old fragment not found"
    if count > 1:
        return f"ERROR: old fragment appears {count} times; provide a more unique fragment"
    updated = original.replace(old, new, 1)
    p.write_text(updated, encoding=encoding)
    return f"UPDATED {path}"


# ── Coder-backed tools (these call the CODER model, not the orchestrator) ─────
@tool
def generate_code(
    description: str = "",
    language: str = "",
    signature: str = "",
    requirements: str = "",
    examples: str = "",
    task_description: str = "",
    existing_code: str = "",
) -> str:
    """Generate code with the coder model. Returns code or a realizability reason.
    Use `description/language/signature/requirements/examples` (parity mode) or
    legacy `task_description/existing_code` from earlier demos."""
    # backward compatibility with the old demo prompt contract
    if not description and task_description:
        description = task_description
    if existing_code:
        requirements = (
            f"{requirements}\n\nExisting file content (keep unchanged parts intact):\n{existing_code}"
            if requirements
            else f"Existing file content (keep unchanged parts intact):\n{existing_code}"
        )

    prompt = _build_coder_prompt(description, language, signature, requirements, examples)
    messages = [SystemMessage(content=_CODER_SYSTEM), HumanMessage(content=prompt)]

    try:
        resp = coder_llm.invoke(messages)
    except Exception as e:
        return f"ERROR calling coder model: {e}"

    parsed = _extract_json_object(getattr(resp, "content", ""))
    if parsed is None:
        # fallback to old behavior when model does not obey JSON contract
        raw_content = getattr(resp, "content", "")
        raw = raw_content.strip() if isinstance(raw_content, str) else str(raw_content or "").strip()
        if raw.startswith("```"):
            lines = raw.splitlines()
            raw = "\n".join(lines[1:-1]).strip() if len(lines) > 2 else raw
        return raw or "ERROR: model returned empty response"

    if not parsed.get("realizable", True):
        return f"[NOT REALIZABLE] {parsed.get('reason', 'no reason provided')}"

    code_value = parsed.get("code", "")
    code = code_value.strip() if isinstance(code_value, str) else str(code_value or "").strip()
    if not code:
        return "ERROR: model returned empty code"
    return code


@tool
def create_tool(tool_name: str, description: str) -> str:
    """Create a BRAND-NEW tool for the agent itself (self-extension). The coder writes
    a new @tool function and it is saved into generated_tools/. Use only when the agent
    needs a capability it does not already have."""
    prompt = (
        "Write a single Python function decorated with @tool from langchain_core.tools.\n"
        "Return ONLY the code, no markdown fences. Include a clear docstring.\n\n"
        f"Tool name: {tool_name}\n"
        f"What it should do: {description}\n"
    )
    raw = coder_llm.invoke(prompt).content
    code = raw if isinstance(raw, str) else str(raw)
    if code.strip().startswith("```"):
        lines = code.strip().splitlines()
        code = "\n".join(lines[1:-1]) if len(lines) > 2 else code
    GENERATED_TOOLS_DIR.mkdir(parents=True, exist_ok=True)
    dest = GENERATED_TOOLS_DIR / f"{tool_name}.py"
    dest.write_text(code, encoding="utf-8")
    return f"CREATED new tool '{tool_name}' at {dest}"


# ── Git tools (no push to remote in the demo — safe) ─────────────────────────
@tool
def git_commit(repo_path: str, message: str) -> str:
    """Stage all changes and commit them locally in repo_path. Does NOT push."""
    out = []
    for c in ["git add -A", f'git commit -m "{message}"']:
        r = subprocess.run(c, shell=True, cwd=repo_path, capture_output=True, text=True)
        out.append(f"$ {c}\n{r.stdout}{r.stderr}")
    return "\n".join(out)


# All base tools the orchestrator is allowed to use
BASE_TOOLS = [
    get_weather,
    get_city,
    read_file,
    write_file,
    list_files,
    run_bash,
    run_python,
    web_search,
    fetch_url,
    fetch_url_render,
    change_file,
    generate_code,
    create_tool,
    git_commit,
]