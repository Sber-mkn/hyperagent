import json
import logging
import pathlib
import subprocess
import threading

import pika

from rabbitmq.rabbitmq_service import RabbitMQBase

USER = "client"
PASSWORD = "12345"
EXCHANGE = "agent_exchange"
CLIENT_QUEUE = "client_queue"
ROUTING_KEY = "agent"
WORKDIR = pathlib.Path("workdir")

logger = logging.getLogger(__name__)


class RabbitMQClient(RabbitMQBase):
    def __init__(
            self,
            user=USER,
            password=PASSWORD,
            exchange=EXCHANGE,
            queue=CLIENT_QUEUE,
            routing_key=ROUTING_KEY,
    ):
        super().__init__(user, password, exchange, queue, routing_key)
        self.is_ready = False
        self.pending_message = None
        self.ready_event = threading.Event()

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
                print(f"{message.get('message')} ({message.get('message_type')})")
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
                    {"stdout": result.stdout},
                )

                ch.basic_ack(delivery_tag=method.delivery_tag)

            else:
                logger.warning("Unknown message type: %s", message_type)
                ch.basic_ack(delivery_tag=method.delivery_tag)

        except Exception as e:
            logger.exception("Error processing client message: %s", e)
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)

    def publish(self):
        if self.pending_message is not None:
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

            message = {"task": user_input, "command": "start"}
            self.pending_message = message
            self.connection.add_callback_threadsafe(self.publish)
