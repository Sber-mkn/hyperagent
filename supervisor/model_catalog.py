"""Answer the client's "which models can the server reach" questions.

Model addresses are always resolved from the server's side: the client picks
where the backend should look, and only the backend ever contacts it. Listing
therefore has to happen here rather than in the client process, which sits on
a different machine and would resolve the very same address differently.
"""

import os

import requests

TAGS_TIMEOUT = 10
HYPER = "hyper"
CUSTOM = "ollama"


def hyper_ollama_url() -> str:
    return os.getenv("HYPER_OLLAMA_URL", "http://host.docker.internal:11434")


def resolve_base_url(url: str) -> str:
    """A loopback address means "the machine hosting the backend", which from
    inside this container is reachable as host.docker.internal (docker-compose
    maps it to the host gateway)."""
    normalized = (url or "").strip().rstrip("/")
    for loopback_host in ("localhost", "127.0.0.1"):
        normalized = normalized.replace(f"://{loopback_host}", "://host.docker.internal")
    return normalized


def list_models(provider: str, url: str = "") -> list[str]:
    base_url = hyper_ollama_url() if provider == HYPER else resolve_base_url(url)
    if not base_url:
        raise ValueError("No model address configured")

    response = requests.get(f"{base_url}/api/tags", timeout=TAGS_TIMEOUT)
    response.raise_for_status()
    models = response.json().get("models", [])
    return sorted(
        {str(model["name"]) for model in models if isinstance(model, dict) and model.get("name")}
    )
