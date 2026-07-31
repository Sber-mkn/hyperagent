"""Runtime settings for the mutable agent."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

AGENT_DIR = Path(__file__).resolve().parent
REPO_ROOT = AGENT_DIR.parent

load_dotenv(AGENT_DIR / ".env")

# Скиллы лежат внутри каталога агента: это и персональный том, и рабочее
# дерево git, поэтому они свои у каждого пользователя и версионируются.
DATA_DIR = Path(os.getenv("V3_DATA_DIR", AGENT_DIR / "data"))
AGENT_WORKDIR = Path(os.getenv("AGENT_WORKDIR", REPO_ROOT / "workdir"))

_docker_constitution = Path("/hyperagent/constitution")
CONSTITUTION_DIR = Path(
    os.getenv(
        "CONSTITUTION_DIR",
        _docker_constitution if _docker_constitution.is_dir() else REPO_ROOT / "constitution",
    )
)


def ollama_chat_url(base_url: str) -> str:
    """Turn a bare Ollama base URL into the /api/chat endpoint OllamaClient posts
    to, resolved from where the agent actually runs. An address is always given
    from the server's point of view, so a loopback host means "the machine
    hosting the backend" — which from inside this container is host.docker.internal
    (docker-compose maps it to the host gateway)."""
    normalized = base_url.strip().rstrip("/")
    for loopback_host in ("localhost", "127.0.0.1"):
        normalized = normalized.replace(f"://{loopback_host}", "://host.docker.internal")
    if normalized.endswith("/api/chat"):
        return normalized
    return normalized + "/api/chat"


HYPER_OLLAMA_URL = os.getenv("HYPER_OLLAMA_URL", "http://host.docker.internal:11434")
OLLAMA_URL = (
    os.getenv("OLLAMA_URL") or os.getenv("OLLAMA_CHAT_URL") or ollama_chat_url(HYPER_OLLAMA_URL)
)
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "ollama").strip().lower()
OPENAI_BASE_URL = os.getenv("OPENROUTER_BASE_URL") or os.getenv(
    "OPENAI_BASE_URL", "https://api.openai.com/v1"
)
OPENAI_API_KEY = os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENAI_API_KEY")
AGENT_MODEL = os.getenv("AGENT_MODEL", "ornith:35b")
SUMMARIZER_MODEL = os.getenv("SUMMARIZER_MODEL", AGENT_MODEL)

L2_TOKEN_BUDGET = int(os.getenv("V3_L2_TOKEN_BUDGET", "15000"))
MAX_ITERATIONS = int(os.getenv("V3_MAX_ITERATIONS", "20"))
MAX_OUTPUT_TOKENS = int(os.getenv("V3_MAX_OUTPUT_TOKENS", "2048"))
AGENT_NUM_CTX = int(os.getenv("AGENT_NUM_CTX", "110000"))
