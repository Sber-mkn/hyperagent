import json

from agent_immutable.runtime import get_rabbitmq
from database.agent.crud import add_message
import contextlib

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
        return {"error": f"Unknown command type: {command_type}"}


def on_end_message(message) -> None:
    add_message(_llm_message_to_dict(message))


def _llm_message_to_dict(message) -> dict:
    return {
        "done": message.done,
        "done_reason": message.done_reason,
        "role": message.role,
        "thinking": message.thinking,
        "content": message.content,
        "tool_calls": message.tool_calls,
        "tool_call_id": message.tool_call_id,
        "provider": message.provider,
        "model": message.model,
        "tokens_prompt": message.tokens.prompt if message.tokens else None,
        "tokens_response": message.tokens.response if message.tokens else None,
        "duration_load": message.duration.load if message.duration else None,
        "duration_prompt": message.duration.prompt if message.duration else None,
        "duration_response": message.duration.response if message.duration else None,
        "dt": message.dt,
    }


def on_think(message: str) -> None:
    _send_agent_message("think", message)


def on_content(message: str) -> None:
    _send_agent_message("content", message)


def on_title(title: str) -> None:
    _send_agent_message("title", title)


def on_start_message(model: str) -> None:
    _send_agent_message("start", model)


def on_tool_call(name: str, arguments, target: str, result_preview: str) -> None:
    if isinstance(arguments, str):
        with contextlib.suppress(json.JSONDecodeError, TypeError):
            arguments = json.loads(arguments)
    args_text = (
        json.dumps(arguments, ensure_ascii=False) if isinstance(arguments, dict) else str(arguments)
    )
    _send_agent_message("tool_call", f"{name}({args_text}) [{target}] -> {result_preview}")


def _send_agent_message(message_type: str, message: dict | str) -> None:
    get_rabbitmq().publish_message(
        {"type": "agent_message", "message_type": message_type, "message": message},
        routing_key=CLIENT_ROUTING_KEY,
    )
