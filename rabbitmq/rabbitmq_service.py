import json
import logging
from abc import ABC, abstractmethod

import pika
from pika.exceptions import AMQPError

logger = logging.getLogger(__name__)


class RabbitMQBase(ABC):
    def __init__(self, user, password, exchange, queue, routing_key):
        rabbitmq_url = f"amqp://{user}:{password}@rabbitmq:5672/"
        self.connection = pika.BlockingConnection(pika.URLParameters(rabbitmq_url))
        self.exchange = exchange
        self.queue = queue
        self.routing_key = routing_key
        self.channel = self.connection.channel()
        logger.info("RabbitMQ connection established")

    def publish_message(self, message: dict, routing_key=None):
        body = json.dumps(message, ensure_ascii=False)
        if not routing_key:
            routing_key = self.routing_key
        try:
            self.channel.basic_publish(
                exchange=self.exchange,
                routing_key=routing_key,
                body=body,
                properties=pika.BasicProperties(delivery_mode=2, content_type="application/json"),
            )
        except pika.exceptions.AMQPError as e:
            logger.exception(e)
        logger.info(f"Message published: {message.get('command')}")

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
