from __future__ import annotations

from agent.config import (
    AGENT_MODEL,
    OLLAMA_CHAT_URL,
    OPENROUTER_API_KEY,
    OPENROUTER_BASE_URL,
    PROVIDER,
    REQUEST_TIMEOUT,
)
from agent.llminterface.client.llm_client import LLMClient
from agent.llminterface.client.providers.ollama_client import OllamaClient
from agent.llminterface.client.providers.openrouter_client import OpenRouterClient


def build_client() -> LLMClient:
    if PROVIDER == "openrouter":
        return OpenRouterClient(
            api_key=OPENROUTER_API_KEY,
            base_url=OPENROUTER_BASE_URL,
            timeout=REQUEST_TIMEOUT,
        )
    if PROVIDER == "ollama":
        return OllamaClient(url=OLLAMA_CHAT_URL, timeout=REQUEST_TIMEOUT)
    raise ValueError("LLM_PROVIDER must be 'openrouter' or 'ollama'")


def default_model() -> str:
    return AGENT_MODEL
