"""Runtime settings for the mutable agent."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


AGENT_DIR = Path(__file__).resolve().parent
REPO_ROOT = AGENT_DIR.parent

load_dotenv(AGENT_DIR / ".env")

DATA_DIR = Path(os.getenv("V3_DATA_DIR", REPO_ROOT / "logs" / "agent_data"))
AGENT_WORKDIR = Path(os.getenv("AGENT_WORKDIR", REPO_ROOT / "workdir"))

_docker_constitution = Path("/hyperagent/constitution")
CONSTITUTION_DIR = Path(
    os.getenv(
        "CONSTITUTION_DIR",
        _docker_constitution if _docker_constitution.is_dir() else REPO_ROOT / "constitution",
    )
)

OLLAMA_URL = os.getenv("OLLAMA_URL") or os.getenv(
    "OLLAMA_CHAT_URL", "http://localhost:11434/api/chat"
)
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "ollama").strip().lower()
OPENAI_BASE_URL = os.getenv("OPENROUTER_BASE_URL") or os.getenv(
    "OPENAI_BASE_URL", "https://api.openai.com/v1"
)
OPENAI_API_KEY = os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENAI_API_KEY")
AGENT_MODEL = os.getenv("AGENT_MODEL", "ornith:9b")
SUMMARIZER_MODEL = os.getenv("SUMMARIZER_MODEL", AGENT_MODEL)

L2_TOKEN_BUDGET = int(os.getenv("V3_L2_TOKEN_BUDGET", "15000"))
MAX_ITERATIONS = int(os.getenv("V3_MAX_ITERATIONS", "20"))
MAX_OUTPUT_TOKENS = int(os.getenv("V3_MAX_OUTPUT_TOKENS", "2048"))
AGENT_NUM_CTX = int(os.getenv("AGENT_NUM_CTX", "110000"))
