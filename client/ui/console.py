from getpass import getpass
from typing import Any

LOCAL_MODELS = ("auto", "Model 1", "Model 2")


def _read_non_empty(prompt: str, secret: bool = False) -> str:
    while True:
        value = getpass(prompt).strip() if secret else input(prompt).strip()
        if value:
            return value
        print("Value cannot be empty.")


def _choose_agent_type() -> str:
    print("Choose agent type:")
    print("  1. local_agent")
    print("  2. api_router")
    while True:
        value = input("Agent type [1, 2]: ").strip().lower()
        if value == "1":
            return "local"
        if value == "2":
            return "api"
        print("Enter 1 or 2: ")


def _choose_local_model() -> str:
    print("Choose local model:")
    for index, model in enumerate(LOCAL_MODELS, start=1):
        print(f"  {index}. {model}")
    while True:
        value = input("Local model [1-3 or name]: ").strip()
        if value.isdigit() and 1 <= int(value) <= len(LOCAL_MODELS):
            return LOCAL_MODELS[int(value) - 1]
        for model in LOCAL_MODELS:
            if value.lower() == model.lower():
                return model
        print("Enter 1, 2, 3, or one of the shown model names.")


def read_login_payload() -> tuple[str, str, str, dict]:
    login = _read_non_empty("Login: ")
    password = _read_non_empty("Password: ", secret=True)
    agent_type = _choose_agent_type()

    if agent_type == "api":
        return (
            login,
            password,
            agent_type,
            {
                "OPENROUTER_API_KEY": _read_non_empty("OPENROUTER_API_KEY: ", secret=True),
                "AGENT_MODEL": _read_non_empty("AGENT_MODEL: "),
            },
        )

    return (
        login,
        password,
        agent_type,
        {"AGENT_MODEL": _choose_local_model()},
    )


class ConsoleClientUI:
    def __init__(self):
        self._stream_kind = None
        self.chat_id: int | None = None

    def on_ready(self) -> None:
        print("\nHyperagent is ready. Enter request: ")

    def on_result(self, message: dict[str, Any]) -> None:
        print("\nResult received")
        print(f"Status: {message.get('status')}")
        print(f"Result: {message.get('result')}")

    def on_agent_message(self, kind: str, text: str) -> None:
        self._print_agent_message(kind, text)

    @staticmethod
    def on_waiting_result() -> None:
        print("Waiting for result...")

    @staticmethod
    def on_unknown_message(message_type: str) -> None:
        print(f"\nUnknown message type: {message_type}")

    def input_loop(self, client) -> None:
        while True:
            client.ready_event.wait()
            client.ready_event.clear()

            try:
                user_input = input("").strip()
                user_input = user_input.encode("utf-8", errors="replace").decode("utf-8")
            except EOFError:
                print("\nStdin closed, exiting")
                break

            if not user_input:
                client.ready_event.set()
                continue

            if self.chat_id is None:
                self.chat_id = int(client.create_chat("Console chat")["id"])

            client.send_task(user_input, self.chat_id)

    def _print_agent_message(self, kind: str, text: str) -> None:
        if kind in ("think", "content"):
            if self._stream_kind != kind:
                label = "Думает" if kind == "think" else "Ответ"
                print(f"\n\n{label}: ", end="", flush=True)
                self._stream_kind = kind
            print(text, end="", flush=True)
        else:
            self._stream_kind = None
            if kind == "title":
                print(f"\n\n=== {text} ===")
            elif kind == "start":
                print(f"\n\n--- Начало ответа модели {text} ---")
            elif kind == "tool_call":
                print(f"\n\n[Инструмент] {text}")
            else:
                print(f"\n\n{text} ({kind})")
