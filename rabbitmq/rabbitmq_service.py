import json
import logging
import os
import uuid
from abc import ABC, abstractmethod

import pika
from pika.exceptions import AMQPError

logger = logging.getLogger(__name__)
DEFAULT_RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "rabbitmq")
DEFAULT_RABBITMQ_PORT = int(os.getenv("RABBITMQ_PORT", "5672"))


class RequestResponseTimeoutError(TimeoutError):
    pass


class RabbitMQBase(ABC):
    def __init__(
        self,
        user,
        password,
        exchange,
        queue,
        routing_key,
        host: str | None = None,
        port: int | str | None = None,
    ):
        host = host or DEFAULT_RABBITMQ_HOST
        port = int(port or DEFAULT_RABBITMQ_PORT)
        rabbitmq_url = f"amqp://{user}:{password}@{host}:{port}/"
        self.connection = pika.BlockingConnection(pika.URLParameters(rabbitmq_url))
        self.exchange = exchange
        self.queue = queue
        self.routing_key = routing_key
        self.channel = self.connection.channel()
        logger.info("RabbitMQ connection established")

        self.rpc_channel = None
        self.reply_queue = None

    def publish_message(self, message: dict | str, routing_key: str | None = None):
        body = json.dumps(message, ensure_ascii=False)
        if routing_key is None:
            routing_key = self.routing_key
        try:
            self.channel.basic_publish(
                exchange=self.exchange,
                routing_key=routing_key,
                body=body,
                properties=pika.BasicProperties(delivery_mode=2, content_type="application/json"),
            )
        except AMQPError as e:
            logger.exception(e)
        logger.info(f"Message published: {message.get('type')}")

    def _ensure_reply_queue(self):
        if self.reply_queue is not None:
            return

        self.rpc_channel = self.connection.channel()
        self.reply_queue = self.rpc_channel.queue_declare(
            queue="", exclusive=True, auto_delete=False
        ).method.queue

    def request_response(self, message: dict, routing_key: str | None = None, timeout=60):
        self._ensure_reply_queue()

        if routing_key is None:
            routing_key = self.routing_key

        body = json.dumps(message, ensure_ascii=False)
        correlation_id = str(uuid.uuid4())

        self.rpc_channel.basic_publish(
            exchange=self.exchange,
            routing_key=routing_key,
            body=body,
            properties=pika.BasicProperties(
                content_type="application/json",
                correlation_id=correlation_id,
                reply_to=self.reply_queue,
            ),
        )

        try:
            for method, properties, body in self.rpc_channel.consume(
                queue=self.reply_queue,
                auto_ack=True,
                inactivity_timeout=timeout,
            ):
                if method is None:
                    raise RequestResponseTimeoutError("Request response timeout")

                if properties.correlation_id != correlation_id:
                    continue

                return json.loads(body.decode("utf-8"))

        finally:
            self.rpc_channel.cancel()

    def send_response(self, reply_to: str, correlation_id: str, response: dict) -> None:
        self.channel.basic_publish(
            exchange="",
            routing_key=reply_to,
            body=json.dumps(response, ensure_ascii=False),
            properties=pika.BasicProperties(
                content_type="application/json",
                correlation_id=correlation_id,
            ),
        )

    def start_consuming(self):
        self.channel.basic_qos(prefetch_count=1)
        self.channel.basic_consume(queue=self.queue, on_message_callback=self.receive_message)
        logger.info(f"Start consuming: {self.queue}")
        try:
            self.channel.start_consuming()
        except pika.exceptions.AMQPConnectionError:
            logger.error("RabbitMQ connection failed")
            raise

    @abstractmethod
    def receive_message(self, ch, method, properties, body):
        pass
