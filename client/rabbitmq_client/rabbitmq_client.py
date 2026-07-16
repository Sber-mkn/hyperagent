import json
import logging
import os
import pathlib
import threading

import pika

from agent.tools import execute_tool
from rabbitmq.rabbitmq_service import RabbitMQBase

USER = "client"
PASSWORD = "12345"
EXCHANGE = "agent_exchange"
CLIENT_QUEUE = "client_queue"
ROUTING_KEY = "supervisor"
SUPERVISOR_ROUTING_KEY = "supervisor"
RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "localhost")
RABBITMQ_PORT = int(os.getenv("RABBITMQ_PORT", "5672"))
WORKDIR = pathlib.Path(os.getenv("CLIENT_WORKDIR", "workdir"))
CHAT_ID = 1

logger = logging.getLogger(__name__)


class RabbitMQClient(RabbitMQBase):
    def __init__(
        self,
        user=USER,
        password=PASSWORD,
        exchange=EXCHANGE,
        queue=CLIENT_QUEUE,
        routing_key=ROUTING_KEY,
        host=RABBITMQ_HOST,
        port=RABBITMQ_PORT,
    ):
        super().__init__(user, password, exchange, queue, routing_key, host=host, port=port)
        self.is_ready = False
        self.pending_message = None
        self.agent_session = {}
        self.ready_event = threading.Event()
        self._stream_kind = None  # "think"/"content"/None — для непрерывного вывода чанков

    def send_login(
        self,
        login: str,
        password: str,
        agent_type: str,
        agent_config: dict[str, str],
    ) -> None:
        self.agent_session = {
            "agent_type": agent_type,
            "agent_config": agent_config,
        }
        self.publish_message(
            {
                "type": "login",
                "login": login,
                "password": password,
                **self.agent_session,
            },
            routing_key=SUPERVISOR_ROUTING_KEY,
        )

    def receive_message(self, ch, method, properties, body):
        try:
            message = json.loads(body.decode("utf-8"))
            message_type = message.get("type", "")
            logger.info("Received message: %s", message_type)

            if message_type == "ready":
                self.ready_event.set()
                print("\nHyperagent is ready. Enter request: ")
                ch.basic_ack(delivery_tag=method.delivery_tag)

            elif message_type == "result":
                print("\nResult received")
                print(f"Status: {message.get('status')}")
                print(f"Result: {message.get('result')}")
                self.is_ready = False
                ch.basic_ack(delivery_tag=method.delivery_tag)

            elif message_type == "agent_message":
                self._print_agent_message(message.get("message_type"), message.get("message"))
                ch.basic_ack(delivery_tag=method.delivery_tag)

            elif message_type == "client_command":
                WORKDIR.mkdir(parents=True, exist_ok=True)
                prev_cwd = os.getcwd()
                try:
                    os.chdir(WORKDIR)
                    _, result = execute_tool(message.get("command", {}))
                finally:
                    os.chdir(prev_cwd)

                self.send_response(
                    properties.reply_to,
                    properties.correlation_id,
                    {"result": str(result)},
                )

                ch.basic_ack(delivery_tag=method.delivery_tag)

            else:
                logger.warning("Unknown message type: %s", message_type)
                ch.basic_ack(delivery_tag=method.delivery_tag)

        except Exception as e:
            logger.exception("Error processing client message: %s", e)
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)

    def _print_agent_message(self, kind: str, text: str) -> None:
        """Печатает чанки think/content единым потоком вместо строки на каждый чанк."""
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

    def publish(self):
        if self.pending_message is not None:
            if self.agent_session:
                self.pending_message["agent_session"] = self.agent_session
            body = json.dumps(self.pending_message, ensure_ascii=False)
            self.channel.basic_publish(
                exchange=self.exchange,
                routing_key=self.routing_key,
                body=body,
                properties=pika.BasicProperties(
                    delivery_mode=2,
                    content_type="application/json",
                ),
            )
            print("Waiting for result...")
            self.pending_message = None

    def input_loop(self):
        while True:
            self.ready_event.wait()
            self.ready_event.clear()

            try:
                user_input = input("").strip()
                user_input = user_input.encode("utf-8", errors="replace").decode("utf-8")
            except EOFError:
                print("\nStdin closed, exiting")
                break

            if not user_input:
                self.ready_event.set()
                continue

            message = {"task": user_input, "command": "start", "chat_id": CHAT_ID}
            self.pending_message = message
            self.connection.add_callback_threadsafe(self.publish)
