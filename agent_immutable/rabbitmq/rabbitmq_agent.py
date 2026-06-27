import json
import pika
from agent_immutable.rabbitmq.message_errors import *
from pika import exceptions

RABBITMQ_URL = "amqp://agent:12345@rabbitmq:5672/"
EXCHANGE = "agent_exchange"
AGENT_QUEUE = "agent_queue"
ROUTING_KEY = "supervisor"

class RabbitMQServise:
    def __init__(self, rabbitmq_url = RABBITMQ_URL,
                 exchange=EXCHANGE, queue=AGENT_QUEUE, routing_key=ROUTING_KEY):
        self.command = None
        self.error_text = None
        self.snapshot_text = None
        self.connection = pika.BlockingConnection(pika.URLParameters(rabbitmq_url))
        self.exchange = exchange
        self.queue = queue
        self.routing_key = routing_key
        self.channel = self.connection.channel()
    def receive_command(self, ch, method, properties, body):
        message = json.loads(body.decode("utf-8"))
        self.command = message.get("command", "")
        self.error_text = message.get("error_text", None)
        self.snapshot_text = message.get("snapshot_text", None)
        ch.stop_consuming()
    def start_consuming(self):
        self.channel.basic_qos(prefetch_count=1)
        self.channel.basic_consume(queue=self.queue, on_message_callback=self.receive_command)
        self.channel.start_consuming()
    def send_commit(self, commit_sha, commit_text):
        message = {
            "type": "commit",
            "commit_sha": commit_sha,
            "commit_text": commit_text
        }
        body = json.dumps(message)
        try:
            self.channel.basic_publish(
                exchange=self.exchange,
                routing_key=self.routing_key,
                body=body,
                properties=pika.BasicProperties(
                    delivery_mode=2,
                    content_type="application/json"
                )
            )
        except pika.exceptions.AMQPConnectionError as e:
            raise ConnectionLostError(
                f"{commit_sha}: {e}"
            ) from e
        except pika.exceptions.UnroutableError as e:
            raise MessagePublishError(
                message=f"Message was not delivered: {e}",
                exchange=self.exchange,
                routing_key=self.routing_key,
                body=body
            ) from e
        except pika.exceptions.AMQPChannelError as e:
            raise ChannelError(
                f"{commit_sha}: {e}"
            ) from e
    def send_error(self, error_text):
        message = {
            "type": "error",
            "error": error_text
        }
        body = json.dumps(message)
        try:
            self.channel.basic_publish(
                exchange=self.exchange,
                routing_key=self.routing_key,
                body=body,
                properties=pika.BasicProperties(
                    delivery_mode=2,
                    content_type="application/json"
                )
            )
        except pika.exceptions.AMQPConnectionError as e:
            raise ConnectionLostError(
                f"{error_text}: {e}"
            ) from e
        except pika.exceptions.UnroutableError as e:
            raise MessagePublishError(
                message=f"Message was not delivered: {e}",
                exchange=self.exchange,
                routing_key=self.routing_key,
                body=body
            ) from e
        except pika.exceptions.AMQPChannelError as e:
            raise ChannelError(
                f"{error_text}: {e}"
            ) from e
    def send_ack(self):
        message = {
            "type": "ack"
        }
        body = json.dumps(message)
        try:
            self.channel.basic_publish(
                exchange=self.exchange,
                routing_key=self.routing_key,
                body=body,
                properties=pika.BasicProperties(
                    delivery_mode=2,
                    content_type="application/json"
                )
            )
        except pika.exceptions.AMQPError as e:
            raise MessagePublishError(
                message=f"ACK was not delivered: {e}",
                exchange=self.exchange,
                routing_key=self.routing_key,
                body=body
            ) from e

    def get_command(self):
        return self.command, self.error_text, self.snapshot_text