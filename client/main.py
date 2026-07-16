import logging
import pathlib
import sys
import threading
from getpass import getpass

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from client.rabbitmq_client.rabbitmq_client import RabbitMQClient

logger = logging.getLogger(__name__)
LOCAL_MODELS = ("auto", "Model 1", "Model 2")

def _prompt_non_empty(prompt: str, secret: bool = False) -> str:
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


def _prompt_login_payload() -> tuple[str, str, str, dict[str, str]]:
    login = _prompt_non_empty("Login: ")
    password = _prompt_non_empty("Password: ", secret=True)
    agent_type = _choose_agent_type()

    if agent_type == "api":
        return (
            login,
            password,
            agent_type,
            {
                "OPENROUTER_API_KEY": _prompt_non_empty("OPENROUTER_API_KEY: ", secret=True),
                "AGENT_MODEL": _prompt_non_empty("AGENT_MODEL: "),
            },
        )

    return (
        login,
        password,
        agent_type,
        {"AGENT_MODEL": _choose_local_model()},
    )


if __name__ == "__main__":
    login_payload = _prompt_login_payload()
    client = RabbitMQClient()
    logger.info("Starting client")
    client.send_login(*login_payload)
    authenticated = client.is_authenticated.wait(timeout=300)
    if not authenticated:
        logger.exception("Authentication timeout or failed.")
        sys.exit(1)

    input_thread = threading.Thread(target=client.input_loop, daemon=True)
    input_thread.start()
    try:
        client.start_consuming()
    except KeyboardInterrupt:
        client.send_logout()
        print("\nClient stopped")
        sys.exit(0)
