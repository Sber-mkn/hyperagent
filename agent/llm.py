"""LLM clients for the agent (LOCAL ONLY — no cloud API).

Four model roles (matches the team's architecture):
  - orchestrator: decides what to do, picks tools (the "brain")
  - coder:        writes the actual code when asked (the "hands that type code")
  - namer:        produces a short conversation title
  - reflector:    checks whether the final answer is good enough

Everything runs on local Ollama. Override any model via env vars; defaults below.
"""

import os

from dotenv import load_dotenv
from langchain_ollama import ChatOllama

load_dotenv()

# Local Ollama endpoint (override OLLAMA_BASE_URL if your server runs elsewhere).
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")

ORCHESTRATOR_MODEL = os.getenv("ORCHESTRATOR_MODEL", "qwen2.5-coder:3b")
CODER_MODEL = os.getenv("CODER_MODEL", "qwen2.5-coder:3b")
NAMER_MODEL = os.getenv("NAMER_MODEL", ORCHESTRATOR_MODEL)
REFLECTOR_MODEL = os.getenv("REFLECTOR_MODEL", ORCHESTRATOR_MODEL)

# temperature=0 on the orchestrator -> stable, deterministic tool calls
orchestrator_llm = ChatOllama(model=ORCHESTRATOR_MODEL, base_url=OLLAMA_BASE_URL, temperature=0)

# a little creativity is fine for the coder, but keep it low for correctness
coder_llm = ChatOllama(model=CODER_MODEL, base_url=OLLAMA_BASE_URL, temperature=0.2)

# the namer is allowed to be a bit more creative for a snappy title
namer_llm = ChatOllama(model=NAMER_MODEL, base_url=OLLAMA_BASE_URL, temperature=0.8)

# the reflector judges correctness, so keep it low temperature
reflector_llm = ChatOllama(model=REFLECTOR_MODEL, base_url=OLLAMA_BASE_URL, temperature=0.2)
