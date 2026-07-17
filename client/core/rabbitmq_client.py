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
AGENT_EXCHANGE = "agent_exchange"
AGENT_ROUTING_KEY = "agent"
EXCHANGE = "router_exchange"
ROUTER_QUEUE = "router_queue"
CLIENT_QUEUE = "client_queue"
ROUTING_KEY = "router"
SUPERVISOR_ROUTING_KEY = "supervisor"
RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "localhost")
RABBITMQ_PORT = int(os.getenv("RABBITMQ_PORT", "5672"))
DEFAULT_WORKDIR = pathlib.Path(os.getenv("CLIENT_WORKDIR", "workdir"))

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
        self.work_dir = DEFAULT_WORKDIR
        self.allow_commands_for_request = False
        self.ready_event = threading.Event()
        self.event_handler = event_handler
        self.login = None

    def set_work_dir(self, work_dir: str | None) -> None:
        self.work_dir = pathlib.Path(work_dir) if work_dir else DEFAULT_WORKDIR

    def _emit(self, event_name: str, *args) -> None:
        handler = getattr(self.event_handler, event_name, None)
        if handler is not None:
            handler(*args)

    def send_login(
        self,
        login: str,
        password: str,
    ) -> bool:
        response = self.request_response(
            {
                "type": "login",
                "login": login,
                "password": password,
            },
            routing_key="router",
            timeout=300,
        )
        if response.get("type") == "login_response":
            self.login = login
            self._reconnect_to_personal(response)
            self.publish_message({"type": "login"}, routing_key=SUPERVISOR_ROUTING_KEY)
            return True

        self._emit(
            "on_login_error",
            response.get("error") or response.get("message") or "Invalid login or password",
        )
        return False

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
                work_dir = self.work_dir
                work_dir.mkdir(parents=True, exist_ok=True)
                command_id = properties.correlation_id or str(method.delivery_tag)
                command = message.get("command", "")
                command_info = {
                    "id": command_id,
                    "command": command,
                    "cwd": str(work_dir),
                }
                self._emit(
                    "on_client_command_start",
                    command_info,
                )
                if self._can_run_command(command_info):
                    result = subprocess.run(
                        command,
                        cwd=work_dir,
                        shell=True,
                        capture_output=True,
                        text=True,
                    )
                    response = {
                        "stdout": result.stdout,
                        "stderr": result.stderr,
                        "returncode": result.returncode,
                        "command": command,
                        "cwd": str(work_dir),
                    }
                else:
                    response = {
                        "stdout": "",
                        "stderr": "read only",
                        "returncode": 1,
                        "command": command,
                        "cwd": str(work_dir),
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

    def _reconnect_to_personal(self, credentials: dict):
        self.connection.close()

        personal_url = (
            f"amqp://{credentials['rabbitmq_user']}:{credentials['rabbitmq_password']}"
            f"@{credentials['rabbitmq_host']}:{credentials['rabbitmq_port']}/"
        )

        self.connection = pika.BlockingConnection(pika.URLParameters(personal_url))
        self.channel = self.connection.channel()

        self.exchange = AGENT_EXCHANGE
        self.queue = CLIENT_QUEUE
        self.routing_key = AGENT_ROUTING_KEY
        self._rpc_user = credentials["rabbitmq_user"]
        self._rpc_password = credentials["rabbitmq_password"]
        self._rpc_host = credentials["rabbitmq_host"]
        self._rpc_port = int(credentials["rabbitmq_port"])

        self.channel.basic_qos(prefetch_count=1)
        self.channel.basic_consume(queue=self.queue, on_message_callback=self.receive_message)
        logger.info(
            "Connected to personal RabbitMQ at %s:%s",
            credentials["rabbitmq_host"],
            credentials["rabbitmq_port"],
        )

    def send_logout(self):
        if not self.login:
            return
        temp_connection = None
        try:
            router_url = f"amqp://{USER}:{PASSWORD}@{RABBITMQ_HOST}:{RABBITMQ_PORT}/"
            temp_connection = pika.BlockingConnection(pika.URLParameters(router_url))
            temp_channel = temp_connection.channel()

            temp_channel.basic_publish(
                exchange=EXCHANGE,
                routing_key=ROUTING_KEY,
                body=json.dumps(
                    {
                        "type": "logout",
                        "login": self.login,
                    },
                    ensure_ascii=False,
                ),
                properties=pika.BasicProperties(
                    content_type="application/json",
                    delivery_mode=2,
                ),
            )
            logger.info("Logout message sent to router")
        except Exception as e:
            logger.error(f"Failed to send logout message: {e}")
        finally:
            if temp_connection and not temp_connection.is_closed:
                temp_connection.close()

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
