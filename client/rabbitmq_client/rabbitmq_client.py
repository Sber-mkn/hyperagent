import json
import logging
import os
import pathlib
import subprocess
import threading

import pika

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
        self.is_authenticated = threading.Event()
        self.pending_message = None
        self.agent_session = {}
        self.ready_event = threading.Event()
        self._stream_kind = None
        self.login = None

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
        response = self.request_response(
            {
                "type": "login",
                "login": login,
                "password": password,
                **self.agent_session,
            },
            routing_key="router",
            timeout=300,
        )
        if response.get("type") == "login_response":
            self.login = login
            self._reconnect_to_personal(response)
        else:
            logger.error(f"Login failed: {response.get('error')}")
            os._exit(1)

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
                result = subprocess.run(
                    message.get("command", ""),
                    cwd=WORKDIR,
                    shell=True,
                    capture_output=True,
                    text=True,
                )

                self.send_response(
                    properties.reply_to,
                    properties.correlation_id,
                    {
                        "stdout": result.stdout,
                        "stderr": result.stderr,
                        "returncode": result.returncode,
                    },
                )

                ch.basic_ack(delivery_tag=method.delivery_tag)

            else:
                logger.warning("Unknown message type: %s", message_type)
                ch.basic_ack(delivery_tag=method.delivery_tag)

        except Exception as e:
            logger.exception("Error processing client message: %s", e)
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)

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

        self.channel.basic_qos(prefetch_count=1)
        self.channel.basic_consume(queue=self.queue, on_message_callback=self.receive_message)
        logger.info(f"Connected to personal RabbitMQ at {credentials['rabbitmq_host']}:{credentials['rabbitmq_port']}")
        self.is_authenticated.set()

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
                routing_key=ROUTING_KEY,  # "router"
                body=json.dumps({
                    "type": "logout",
                    "login": self.login,
                }),
                properties=pika.BasicProperties(
                    content_type="application/json",
                    delivery_mode=2,
                )
            )
            logger.info("Logout message sent to router")
        except Exception as e:
            logger.error(f"Failed to send logout message: {e}")
        finally:
            if temp_connection and not temp_connection.is_closed:
                temp_connection.close()


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
