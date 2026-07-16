"""Fetch the list of models a provider currently has available, for the settings UI."""

from __future__ import annotations

import requests

OLLAMA_TAGS_TIMEOUT = 5
OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
OPENROUTER_TIMEOUT = 10
OPENAI_MODELS_URL = "https://api.openai.com/v1/models"
OPENAI_TIMEOUT = 10


def fetch_ollama_models(base_url: str) -> list[str]:
    """List models already pulled on the given Ollama server (its ``ollama list``)."""
    url = base_url.rstrip("/") + "/api/tags"
    response = requests.get(url, timeout=OLLAMA_TAGS_TIMEOUT)
    response.raise_for_status()
    data = response.json()
    names = {
        str(model["name"])
        for model in data.get("models", [])
        if isinstance(model, dict) and model.get("name")
    }
    return sorted(names)


def _fetch_model_ids(url: str, headers: dict[str, str], timeout: int) -> list[str]:
    response = requests.get(url, headers=headers, timeout=timeout)
    response.raise_for_status()
    data = response.json()
    ids = {
        str(model["id"])
        for model in data.get("data", [])
        if isinstance(model, dict) and model.get("id")
    }
    return sorted(ids)


def fetch_openrouter_models(api_key: str = "") -> list[str]:
    """List model ids OpenRouter currently offers. Listing does not require a key,
    but sending one avoids being rate-limited alongside anonymous callers."""
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    return _fetch_model_ids(OPENROUTER_MODELS_URL, headers, OPENROUTER_TIMEOUT)


def fetch_openai_models(api_key: str) -> list[str]:
    """List model ids available to this OpenAI account. Unlike OpenRouter, OpenAI
    requires a key to list models at all -- an empty one will 401."""
    headers = {"Authorization": f"Bearer {api_key}"}
    return _fetch_model_ids(OPENAI_MODELS_URL, headers, OPENAI_TIMEOUT)
