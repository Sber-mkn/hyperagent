"""Environment configuration for the no-framework V3 agent."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

_AGENT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _AGENT_DIR.parent

load_dotenv(_AGENT_DIR / ".env")
load_dotenv(_REPO_ROOT / ".env")

PROVIDER = os.getenv("LLM_PROVIDER", "openrouter").strip().lower()

AGENT_MODEL = os.getenv(
    "AGENT_MODEL",
    os.getenv("ORCHESTRATOR_MODEL", "qwen/qwen3-coder"),
)
SUMMARIZER_MODEL = os.getenv("SUMMARIZER_MODEL", AGENT_MODEL)
MAX_OUTPUT_TOKENS = int(os.getenv("V3_MAX_OUTPUT_TOKENS", "512"))

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
OLLAMA_CHAT_URL = os.getenv("OLLAMA_CHAT_URL", "http://127.0.0.1:11434/api/chat")

_DOCKER_CONSTITUTION = Path("/hyperagent/constitution")
CONSTITUTION_DIR = Path(
    os.getenv(
        "CONSTITUTION_DIR",
        _DOCKER_CONSTITUTION if _DOCKER_CONSTITUTION.exists() else _REPO_ROOT / "constitution",
    )
)

DATA_DIR = Path(os.getenv("V3_DATA_DIR", _AGENT_DIR / "data"))


def _default_agent_root() -> Path:
    docker = Path("/hyperagent/agent")
    return docker if docker.is_dir() else _AGENT_DIR


AGENT_ROOT = Path(os.getenv("AGENT_ROOT") or str(_default_agent_root()))
AGENT_WORKDIR = Path(os.getenv("AGENT_WORKDIR", _REPO_ROOT / "workdir"))
L2_TOKEN_BUDGET = int(os.getenv("V3_L2_TOKEN_BUDGET", "3000"))
MAX_ITERATIONS = int(os.getenv("V3_MAX_ITERATIONS", "20"))
TEXT_ONLY_STEP_LIMIT = int(os.getenv("V3_TEXT_ONLY_STEP_LIMIT", "3"))
REQUEST_TIMEOUT = int(os.getenv("V3_REQUEST_TIMEOUT", "120"))

IDENTITY_PATH = DATA_DIR / "memory" / "identity.md"
CHAT_LOG_PATH = DATA_DIR / "logs" / "chat.jsonl"
DIALOGUE_BLOCKS_PATH = DATA_DIR / "memory" / "dialogue_blocks.json"
