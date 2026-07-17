from datetime import datetime
from typing import Any

from client.core.client_state import (
    ACCESS_ASK,
    ACCESS_FULL,
    ACCESS_READ_ONLY,
    DEFAULT_AGENT_CONFIG,
    DEFAULT_AGENT_TYPE,
    HYPER_OLLAMA_URL,
    MODEL_LOCAL,
    MODEL_OLLAMA,
    MODEL_OPENAI,
    MODEL_OPENROUTER,
    NEW_CHAT_TITLE,
    ClientState,
)
from client.core.rabbitmq_client import RabbitMQClient


class ChatController:
    def __init__(self, state: ClientState) -> None:
        self.state = state
        self.client: RabbitMQClient | None = None
        self.current_chat_id = state.current_chat_id()
        self.chats: list[dict[str, Any]] = []
        self.pending_chat: dict[str, Any] | None = None
        self.pending_session: dict[str, Any] | None = None
        self.awaiting_first_title_chat_ids: set[int] = set()
        self.manual_title_chat_ids: set[int] = set()
        self.local_messages: dict[int, list[dict[str, Any]]] = {}
        self.history_cache: dict[int, list[dict[str, Any]]] = {}
        self.busy_chat_ids: set[int] = set()
        self.request_chat_ids: list[int] = []

    def attach_client(self, client: RabbitMQClient) -> None:
        self.client = client
        client.agent_session = self.agent_session()
        client.set_work_dir(self.settings().get("work_dir") or None)

    def detach_client(self) -> None:
        self.client = None

    def saved_session(self) -> dict[str, Any] | None:
        return self.state.session()

    def begin_login(self, login: str, password: str) -> None:
        self.pending_session = {
            "login": login,
            "password": password,
            "agent_type": DEFAULT_AGENT_TYPE,
            "agent_config": DEFAULT_AGENT_CONFIG,
        }

    def complete_login(self) -> None:
        self.state.save_session(
            self.pending_session["login"],
            self.pending_session["password"],
            self.pending_session["agent_type"],
            self.pending_session["agent_config"],
        )

    def logout(self) -> None:
        self.pending_session = None
        self.chats = []
        self.pending_chat = None
        self.awaiting_first_title_chat_ids.clear()
        self.manual_title_chat_ids.clear()
        self.local_messages.clear()
        self.history_cache.clear()
        self.busy_chat_ids.clear()
        self.request_chat_ids.clear()
        self.current_chat_id = 0
        self.state.set_current_chat(0)
        self.state.clear_session()

    def load_chats(self) -> list[dict[str, Any]]:
        self.chats = self.client.list_chats()
        if self.current_chat_id and all(
            int(chat["id"]) != self.current_chat_id for chat in self.chats
        ):
            self.current_chat_id = 0
            self.state.set_current_chat(0)
        return self.visible_chats()

    def visible_chats(self) -> list[dict[str, Any]]:
        if self.pending_chat is None:
            return list(self.chats)
        return [self.pending_chat, *self.chats]

    def can_create_chat(self) -> bool:
        return self.pending_chat is None

    def create_chat(self) -> dict[str, Any]:
        if self.pending_chat is None:
            self.pending_chat = {
                "id": -1,
                "title": NEW_CHAT_TITLE,
                "updated_at": datetime.now().isoformat(),
                "has_messages": False,
            }
        return self.pending_chat

    def open_chat(self, chat_id: int) -> list[dict[str, Any]]:
        self.current_chat_id = chat_id
        self.state.set_current_chat(chat_id)
        if chat_id <= 0:
            return []
        if self.busy_chat_ids:
            return self.chat_history(chat_id)
        self.history_cache[chat_id] = self.client.get_chat_history(chat_id)
        return self.chat_history(chat_id)

    def send_task(self, text: str, chat_id: int) -> int:
        if self.has_busy_chats():
            raise RuntimeError("Request is already in progress")

        self.client.agent_session = self.agent_session()
        chat_id = self._materialize_chat(chat_id)
        is_first_prompt = not self._chat_has_messages(chat_id)

        self.current_chat_id = chat_id
        self.state.set_current_chat(chat_id)
        self._record_local_message(chat_id, "user", text)
        self.client.add_client_message(chat_id, "user", text)

        if is_first_prompt and chat_id not in self.manual_title_chat_ids:
            self.awaiting_first_title_chat_ids.add(chat_id)

        self.busy_chat_ids.add(chat_id)
        self.request_chat_ids.append(chat_id)
        self.client.send_task(text, chat_id)
        self._mark_chat_has_messages(chat_id)
        return chat_id

    def rename_chat(self, chat_id: int, title: str) -> dict[str, Any]:
        if chat_id <= 0:
            self.pending_chat["title"] = title
            self.manual_title_chat_ids.add(chat_id)
            return self.pending_chat

        chat = self.client.rename_chat(chat_id, title)
        self.manual_title_chat_ids.add(chat_id)
        self.awaiting_first_title_chat_ids.discard(chat_id)
        self._upsert_chat(chat)
        return chat

    def apply_agent_title(self, chat_id: int, title: str) -> dict[str, Any] | None:
        if chat_id not in self.awaiting_first_title_chat_ids:
            return None
        chat = self.client.rename_chat(chat_id, title)
        self.awaiting_first_title_chat_ids.discard(chat_id)
        self._upsert_chat(chat)
        return chat

    def record_agent_message(self, chat_id: int, message_type: str, message: Any) -> None:
        if chat_id <= 0:
            return
        self._record_local_message(chat_id, message_type, message)

    def record_client_command_start(self, chat_id: int, command: dict[str, Any]) -> None:
        self._record_and_save_client_message(chat_id, "client_command_start", command)

    def record_client_command_result(self, chat_id: int, result: dict[str, Any]) -> None:
        self._record_and_save_client_message(chat_id, "client_command_result", result)

    def record_result(self, chat_id: int, result: dict[str, Any]) -> None:
        self._record_and_save_client_message(chat_id, "result", result)

    def record_error(self, chat_id: int, error: str) -> None:
        self._record_and_save_client_message(chat_id, "error", error)

    def finish_request(self, chat_id: int | None = None) -> tuple[int, list[dict[str, Any]]] | None:
        chat_id = self._request_chat_id(chat_id)
        if chat_id is None:
            return None
        self.busy_chat_ids.discard(chat_id)
        self.local_messages.pop(chat_id, None)
        self.history_cache[chat_id] = self.client.get_chat_history(chat_id)
        return chat_id, self.history_cache[chat_id]

    def has_busy_chats(self) -> bool:
        return bool(self.busy_chat_ids)

    def settings(self) -> dict[str, Any]:
        return self.state.settings()

    def save_settings(self, settings: dict[str, Any]) -> None:
        self.state.save_settings(settings)
        if self.client is not None:
            self.client.agent_session = self.agent_session()
            self.client.set_work_dir(settings.get("work_dir") or None)

    def set_model(self, model: str) -> None:
        settings = self.settings()
        settings["model"] = model
        self.save_settings(settings)

    def set_model_choice(self, model: str, model_name: str) -> None:
        settings = self.settings()
        settings["model"] = model
        if model == MODEL_OPENROUTER:
            settings["openrouter_model"] = model_name
        elif model == MODEL_OLLAMA:
            settings["ollama_model"] = model_name
        elif model == MODEL_OPENAI:
            settings["openai_model"] = model_name
        elif model == MODEL_LOCAL:
            settings["local_model"] = model_name
        self.save_settings(settings)

    def set_access(self, access: str) -> None:
        settings = self.settings()
        settings["access"] = access
        self.save_settings(settings)

    def provider_configured(self, model: str) -> bool:
        settings = self.settings()
        if model == MODEL_OPENROUTER:
            return bool(settings["openrouter_api_key"])
        if model == MODEL_OLLAMA:
            return bool(settings["ollama_url"])
        if model == MODEL_OPENAI:
            return bool(settings["openai_api_key"])
        return True

    def model_configured(self, model: str) -> bool:
        settings = self.settings()
        if model == MODEL_OPENROUTER:
            return bool(settings["openrouter_api_key"] and settings["openrouter_model"])
        if model == MODEL_OLLAMA:
            return bool(settings["ollama_url"] and settings["ollama_model"])
        if model == MODEL_OPENAI:
            return bool(settings["openai_api_key"] and settings["openai_model"])
        return True

    def model_fetch_url(self, model: str) -> str:
        if model == MODEL_OLLAMA:
            return str(self.settings().get("ollama_url") or "")
        return HYPER_OLLAMA_URL

    def theme(self) -> str:
        return str(self.settings()["theme"])

    def agent_session(self) -> dict[str, Any]:
        settings = self.settings()
        model = settings["model"]
        agent_type = DEFAULT_AGENT_TYPE
        agent_config = {
            **DEFAULT_AGENT_CONFIG,
            "AGENT_MODEL": settings.get("local_model") or "auto",
        }

        if model == MODEL_OPENROUTER:
            agent_type = "api"
            agent_config = {
                "OPENROUTER_API_KEY": settings["openrouter_api_key"],
                "AGENT_MODEL": settings["openrouter_model"],
            }
        elif model == MODEL_OLLAMA:
            agent_type = "ollama"
            agent_config = {
                "OLLAMA_URL": settings["ollama_url"],
                "AGENT_MODEL": settings.get("ollama_model") or "auto",
            }
        elif model == MODEL_OPENAI:
            agent_type = "openai"
            agent_config = {
                "OPENAI_API_KEY": settings["openai_api_key"],
                "AGENT_MODEL": settings["openai_model"],
            }

        access = settings.get("access") or ACCESS_ASK
        if access not in (ACCESS_READ_ONLY, ACCESS_ASK, ACCESS_FULL):
            access = ACCESS_ASK
        return {
            "agent_type": agent_type,
            "agent_config": agent_config,
            "access": access,
        }

    def chat_history(self, chat_id: int) -> list[dict[str, Any]]:
        return [
            *self.history_cache.get(chat_id, []),
            *self.local_messages.get(chat_id, []),
        ]

    def event_chat_id(self, chat_id: Any) -> int:
        if chat_id:
            return int(chat_id)
        if self.request_chat_ids:
            return self.request_chat_ids[0]
        return self.current_chat_id

    def _materialize_chat(self, chat_id: int) -> int:
        if chat_id > 0:
            return chat_id

        manual_title = chat_id in self.manual_title_chat_ids
        chat = self.client.create_chat(self.pending_chat["title"])
        self.pending_chat = None
        self._upsert_chat(chat)
        real_chat_id = int(chat["id"])
        if manual_title:
            self.manual_title_chat_ids.add(real_chat_id)
        return real_chat_id

    def _record_and_save_client_message(
        self, chat_id: int, message_type: str, message: Any
    ) -> None:
        if chat_id <= 0:
            return
        self._record_local_message(chat_id, message_type, message)
        self.client.add_client_message(chat_id, message_type, message)
        self._mark_chat_has_messages(chat_id)

    def _record_local_message(self, chat_id: int, message_type: str, message: Any) -> None:
        self.local_messages.setdefault(chat_id, []).append(
            {
                "chat_id": chat_id,
                "message_type": message_type,
                "message": message,
                "dt": datetime.now().isoformat(),
            }
        )

    def _mark_chat_has_messages(self, chat_id: int) -> None:
        chat = self._chat_by_id(chat_id)
        chat["has_messages"] = True
        chat["updated_at"] = datetime.now().isoformat()

    def _chat_has_messages(self, chat_id: int) -> bool:
        chat = self._chat_by_id(chat_id)
        return bool(chat["has_messages"])

    def _chat_by_id(self, chat_id: int) -> dict[str, Any]:
        for chat in self.chats:
            if int(chat["id"]) == chat_id:
                return chat
        raise KeyError(chat_id)

    def _upsert_chat(self, chat: dict[str, Any]) -> None:
        chat_id = int(chat["id"])
        for existing in self.chats:
            if int(existing["id"]) == chat_id:
                chat.setdefault("has_messages", existing.get("has_messages", False))
                break
        chat.setdefault("has_messages", False)
        self.chats = [existing for existing in self.chats if int(existing["id"]) != chat_id]
        self.chats.insert(0, chat)

    def _request_chat_id(self, chat_id: int | None) -> int | None:
        if chat_id:
            chat_id = int(chat_id)
            if chat_id in self.request_chat_ids:
                self.request_chat_ids.remove(chat_id)
            return chat_id
        if not self.request_chat_ids:
            return None
        return self.request_chat_ids.pop(0)
