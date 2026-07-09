from agent_immutable.runtime import get_rabbitmq
from database.agent.crud import add_message

SUPERVISOR_ROUTING_KEY = "supervisor"
CLIENT_ROUTING_KEY = "client"


def on_command(command: dict) -> dict:
    rabbitmq = get_rabbitmq()
    command_type = command.get("type")

    if command_type == "git":
        return rabbitmq.request_response(command, routing_key=SUPERVISOR_ROUTING_KEY)
    elif command_type == "server_command":
        return {}
    elif command_type == "client_command":
        return rabbitmq.request_response(command, routing_key=CLIENT_ROUTING_KEY)
    else:
        return {"ok": False, "error": f"Unknown command type: {command_type}"}


def on_end_message(message: dict) -> None:
    add_message(message)


def on_think(message: dict) -> None:
    _send_agent_message("think", message)


def on_content(message: dict) -> None:
    _send_agent_message("content", message)


def _send_agent_message(message_type: str, message: dict) -> None:
    get_rabbitmq().publish_message(
        {"type": "agent_message", "message_type": message_type, "message": message},
        routing_key=CLIENT_ROUTING_KEY,
    )
