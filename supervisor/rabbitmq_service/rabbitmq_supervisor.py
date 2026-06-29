import json
import logging

import pika
from pika import exceptions

from supervisor.message_handler import ack_handler, commit_handler, error_handler, git_handler

logger = logging.getLogger(__name__)

RABBITMQ_URL = "amqp://supervisor:12345@rabbitmq:5672/"
EXCHANGE = "agent_exchange"
QUEUE = "supervisor_queue"
ROUTING_KEY = "agent"


class RabbitMQService:
    def __init__(
        self, rabbitmq_url=RABBITMQ_URL, exchange=EXCHANGE, queue=QUEUE, routing_key=ROUTING_KEY
    ):
        self.connection = pika.BlockingConnection(pika.URLParameters(rabbitmq_url))
        self.exchange = exchange
        self.queue = queue
        self.routing_key = routing_key
        self.channel = self.connection.channel()
        logger.info("RabbitMQ connection established")

    def start_consuming(self):
        self.channel.basic_qos(prefetch_count=1)
        self.channel.basic_consume(queue=self.queue, on_message_callback=self.supervise_agent)
        logger.info(f"Start consuming: {self.queue}")
        try:
            self.channel.start_consuming()
        except pika.exceptions.AMQPConnectionError:
            logger.error("Соединение с RabbitMQ потеряно")
            raise

    def publish_message(self, message: dict):
        body = json.dumps(message, ensure_ascii=False)
        self.channel.basic_publish(
            exchange=self.exchange,
            routing_key=self.routing_key,
            body=body,
            properties=pika.BasicProperties(delivery_mode=2, content_type="application/json"),
        )
        logger.info(f"Message published: {message.get('command')}")

    def send_start_command(self, error_text=None, snapshot_text=None):
        message = {
            "command": "start",
        }
        if error_text:
            message["error_text"] = error_text
        if snapshot_text:
            message["snapshot_text"] = snapshot_text
        self.publish_message(message)

    def send_stop_command(self):
        message = {
            "command": "stop",
        }
        self.publish_message(message)

    def supervise_agent(self, ch, method, properties, body):
        try:
            message = json.loads(body.decode("utf-8"))
            message_type = message.get("type")
            logger.info(f"Message consumed: {message_type}")
            if message_type == "git":
                git_handler(message, self)
                ch.basic_ack(delivery_tag=method.delivery_tag)

            elif message_type == "error":
                error_text = message.get("error")
                error_handler(message)
                self.send_start_command(error_text)
                ch.basic_ack(delivery_tag=method.delivery_tag)
            elif message_type == "ask":
                ack_handler()
                ch.basic_ack(delivery_tag=method.delivery_tag)
            else:
                logger.info(f"Unknown type: {message_type}")
                ch.basic_ack(delivery_tag=method.delivery_tag)
        except Exception as e:
            logger.exception(f"Ошибка при обработке сообщения: {e}")
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)
