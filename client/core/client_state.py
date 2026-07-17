import json
import os
from pathlib import Path
from typing import Any

DEFAULT_AGENT_TYPE = "local"
DEFAULT_AGENT_CONFIG = {"AGENT_MODEL": "auto"}
NEW_CHAT_TITLE = "New Chat"
MODEL_LOCAL = "local"
MODEL_OPENROUTER = "openrouter"
MODEL_OLLAMA = "ollama"
MODEL_OPENAI = "openai"
HYPER_OLLAMA_URL = "http://localhost:11434"
ACCESS_READ_ONLY = "read_only"
ACCESS_ASK = "ask"
ACCESS_FULL = "full_access"
DEFAULT_SETTINGS = {
    "model": MODEL_LOCAL,
    "local_model": "",
    "openrouter_api_key": "",
    "openrouter_model": "",
    "ollama_url": "",
    "ollama_model": "",
    "openai_api_key": "",
    "openai_model": "",
    "theme": "dark",
    "access": ACCESS_ASK,
    "work_dir": "",
}


class ClientState:
    def __init__(self, data_dir: str | Path | None = None):
        self.path = _state_path(data_dir)
        self.data = self._load()
        self.data.setdefault("session", None)
        self.data.setdefault("current_chat_id", 0)
        self.data.setdefault("window", {})
        self.data.setdefault("settings", dict(DEFAULT_SETTINGS))
        self.data["settings"] = {**DEFAULT_SETTINGS, **self.data["settings"]}
        self.data.pop("chats", None)
        self.data.pop("next_chat_id", None)
        self.save()

    def session(self) -> dict[str, Any] | None:
        session = self.data["session"]
        return session if isinstance(session, dict) and session.get("login") else None

    def save_session(
        self,
        login: str,
        password: str,
        agent_type: str,
        agent_config: dict[str, str],
    ) -> None:
        self.data["session"] = {
            "login": login,
            "password": password,
            "agent_type": agent_type,
            "agent_config": agent_config,
        }
        self.save()

    def clear_session(self) -> None:
        self.data["session"] = None
        self.save()

    def current_chat_id(self) -> int:
        return int(self.data["current_chat_id"])

    def set_current_chat(self, chat_id: int) -> None:
        self.data["current_chat_id"] = chat_id
        self.save()

    def window_state(self) -> dict[str, Any]:
        return self.data["window"]

    def save_window_state(self, window_state: dict[str, Any]) -> None:
        self.data["window"] = window_state
        self.save()

    def settings(self) -> dict[str, Any]:
        return dict(self.data["settings"])

    def save_settings(self, settings: dict[str, Any]) -> None:
        self.data["settings"] = {**DEFAULT_SETTINGS, **settings}
        self.save()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self.data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _load(self) -> dict[str, Any]:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError, OSError:
            return {}


def _state_path(data_dir: str | Path | None = None) -> Path:
    if data_dir is not None:
        return Path(data_dir) / "client_state.json"
    base = os.getenv("APPDATA") or os.getenv("LOCALAPPDATA")
    if base:
        return Path(base) / "Hyperagent" / "client_state.json"
    return Path.home() / ".hyperagent" / "client_state.json"
