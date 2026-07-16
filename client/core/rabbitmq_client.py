import json
import logging
import os
import pathlib
import subprocess
import threading
import time
import uuid

import pika

from client.core.client_state import ACCESS_ASK, ACCESS_FULL, ACCESS_READ_ONLY
from rabbitmq.rabbitmq_service import RabbitMQBase

USER = "client"
PASSWORD = "12345"
EXCHANGE = "agent_exchange"
CLIENT_QUEUE = "client_queue"
ROUTING_KEY = "agent"
SUPERVISOR_ROUTING_KEY = "supervisor"
RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "localhost")
RABBITMQ_PORT = int(os.getenv("RABBITMQ_PORT", "5672"))
WORKDIR = pathlib.Path(os.getenv("CLIENT_WORKDIR", "workdir"))

logger = logging.getLogger(__name__)


class RabbitMQClient(RabbitMQBase):
    def __init__(self, event_handler):
        super().__init__(
            USER,
            PASSWORD,
            EXCHANGE,
            CLIENT_QUEUE,
            ROUTING_KEY,
            host=RABBITMQ_HOST,
            port=RABBITMQ_PORT,
        )
        self._rpc_user = USER
        self._rpc_password = PASSWORD
        self._rpc_host = RABBITMQ_HOST
        self._rpc_port = RABBITMQ_PORT
        self.agent_session = {}
        self.allow_commands_for_request = False
        self.ready_event = threading.Event()
        self.event_handler = event_handler

    def _emit(self, event_name: str, *args) -> None:
        handler = getattr(self.event_handler, event_name, None)
        if handler is not None:
            handler(*args)

    def send_login(
        self,
        login: str,
        password: str,
    ) -> None:
        self.publish_message(
            {
                "type": "login",
                "login": login,
                "password": password,
            },
            routing_key=SUPERVISOR_ROUTING_KEY,
        )

    def send_task(self, task: str, chat_id: int) -> None:
        message = {
            "task": task,
            "command": "start",
            "agent_session": {**self.agent_session, "chat_id": chat_id},
        }
        self.connection.add_callback_threadsafe(lambda: self._publish(message))

    def list_chats(self) -> list[dict]:
        response = self._supervisor_request({"type": "client_data", "action": "list_chats"})
        return response["chats"]

    def create_chat(self, title: str) -> dict:
        response = self._supervisor_request(
            {"type": "client_data", "action": "create_chat", "title": title}
        )
        return response["chat"]

    def rename_chat(self, chat_id: int, title: str) -> dict:
        response = self._supervisor_request(
            {
                "type": "client_data",
                "action": "rename_chat",
                "chat_id": chat_id,
                "title": title,
            }
        )
        return response["chat"]

    def get_chat_history(self, chat_id: int) -> list[dict]:
        response = self._supervisor_request(
            {"type": "client_data", "action": "get_history", "chat_id": chat_id}
        )
        return response["messages"]

    def add_client_message(self, chat_id: int, message_type: str, message) -> int:
        response = self._supervisor_request(
            {
                "type": "client_data",
                "action": "add_client_message",
                "chat_id": chat_id,
                "message_type": message_type,
                "message": message,
            }
        )
        return int(response["id"])

    def receive_message(self, ch, method, properties, body):
        try:
            message = json.loads(body.decode("utf-8"))
            message_type = message.get("type", "")
            logger.info("Received message: %s", message_type)

            if message_type == "ready":
                self.allow_commands_for_request = False
                self.ready_event.set()
                self._emit("on_ready")
                ch.basic_ack(delivery_tag=method.delivery_tag)

            elif message_type == "result":
                self._emit("on_result", message)
                ch.basic_ack(delivery_tag=method.delivery_tag)

            elif message_type == "login_error":
                self._emit(
                    "on_login_error",
                    message.get("error") or message.get("message") or "Неправильный пароль",
                )
                ch.basic_ack(delivery_tag=method.delivery_tag)

            elif message_type == "service_unavailable":
                self._emit(
                    "on_service_unavailable",
                    message.get("error") or message.get("message") or "Сервис временно недоступен",
                )
                ch.basic_ack(delivery_tag=method.delivery_tag)

            elif message_type == "agent_message":
                self._emit(
                    "on_agent_message",
                    message.get("message_type"),
                    message.get("message"),
                )
                ch.basic_ack(delivery_tag=method.delivery_tag)

            elif message_type == "error":
                self._emit(
                    "on_agent_message",
                    "error",
                    message.get("error") or message.get("message") or "Agent error",
                )
                ch.basic_ack(delivery_tag=method.delivery_tag)

            elif message_type == "client_command":
                WORKDIR.mkdir(parents=True, exist_ok=True)
                command_id = properties.correlation_id or str(method.delivery_tag)
                command = message.get("command", "")
                command_info = {
                    "id": command_id,
                    "command": command,
                    "cwd": str(WORKDIR),
                }
                self._emit(
                    "on_client_command_start",
                    command_info,
                )
                if self._can_run_command(command_info):
                    result = subprocess.run(
                        command,
                        cwd=WORKDIR,
                        shell=True,
                        capture_output=True,
                        text=True,
                    )
                    response = {
                        "stdout": result.stdout,
                        "stderr": result.stderr,
                        "returncode": result.returncode,
                        "command": command,
                        "cwd": str(WORKDIR),
                    }
                else:
                    response = {
                        "stdout": "",
                        "stderr": "read only",
                        "returncode": 1,
                        "command": command,
                        "cwd": str(WORKDIR),
                    }
                self._emit(
                    "on_client_command_result",
                    {
                        "id": command_id,
                        **response,
                    },
                )

                self.send_response(
                    properties.reply_to,
                    properties.correlation_id,
                    response,
                )

                ch.basic_ack(delivery_tag=method.delivery_tag)

            else:
                logger.warning("Unknown message type: %s", message_type)
                self._emit("on_unknown_message", message_type)
                ch.basic_ack(delivery_tag=method.delivery_tag)

        except Exception as e:
            logger.exception("Error processing client message: %s", e)
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)

    def _publish(self, message: dict) -> None:
        self.allow_commands_for_request = False
        self.publish_message(message)
        self._emit("on_waiting_result")

    def _can_run_command(self, command: dict) -> bool:
        access = self.agent_session.get("access") or ACCESS_ASK
        if access == ACCESS_READ_ONLY:
            return False
        if access == ACCESS_FULL or self.allow_commands_for_request:
            return True

        handler = getattr(self.event_handler, "request_command_permission", None)
        decision = handler(command) if handler is not None else "deny"
        if decision == "allow_all":
            self.allow_commands_for_request = True
            return True
        return decision == "allow"

    def _supervisor_request(self, message: dict, timeout: float = 15.0) -> dict:
        rabbitmq_url = (
            f"amqp://{self._rpc_user}:{self._rpc_password}@{self._rpc_host}:{self._rpc_port}/"
        )
        connection = pika.BlockingConnection(pika.URLParameters(rabbitmq_url))
        channel = connection.channel()
        try:
            reply_queue = channel.queue_declare(
                queue="", exclusive=True, auto_delete=True
            ).method.queue
            correlation_id = str(uuid.uuid4())
            channel.basic_publish(
                exchange=self.exchange,
                routing_key=SUPERVISOR_ROUTING_KEY,
                body=json.dumps(message, ensure_ascii=False),
                properties=pika.BasicProperties(
                    content_type="application/json",
                    correlation_id=correlation_id,
                    reply_to=reply_queue,
                ),
            )

            deadline = time.monotonic() + timeout
            for method, properties, body in channel.consume(
                queue=reply_queue,
                auto_ack=True,
                inactivity_timeout=timeout,
            ):
                if method is None:
                    if time.monotonic() >= deadline:
                        raise TimeoutError("Supervisor request timed out")
                    continue

                if properties.correlation_id != correlation_id:
                    continue

                response = json.loads(body.decode("utf-8"))
                if response.get("error"):
                    raise RuntimeError(str(response["error"]))
                return response

            raise TimeoutError("Supervisor request timed out")
        finally:
            connection.close()
