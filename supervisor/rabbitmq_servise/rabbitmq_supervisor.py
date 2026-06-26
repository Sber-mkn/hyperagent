import json
import pika
from supervisor.rollback import *

RABBITMQ_URL = "amqp://supervisor:12345@rabbitmq:5672/"
EXCHANGE = "agent_exchange"
QUEUE = "supervisor_queue"
ROUTING_KEY = "agent"

class RabbitMQServise:
    def __init__(self, rabbitmq_url = RABBITMQ_URL,
                 exchange=EXCHANGE, queue=QUEUE, routing_key=ROUTING_KEY):
        self.connection = pika.BlockingConnection(pika.URLParameters(rabbitmq_url))
        self.exchange = exchange
        self.queue = queue
        self.routing_key = routing_key
        self.channel = self.connection.channel()
    def start_consuming(self):
        self.channel.basic_qos(prefetch_count=1)
        self.channel.basic_consume(queue=self.queue, on_message_callback=self.supervise_agent)
        self.channel.start_consuming()
    def send_start_command(self, error_text):
        message = {
            "command": "start",
        }
        if error_text:
            message["error_text"] = error_text
        body = json.dumps(message, ensure_ascii=False)
        command_connection = pika.BlockingConnection(pika.URLParameters(RABBITMQ_URL))
        command_channel = self.connection.channel()
        command_channel.basic_publish(
            exchange=self.exchange,
            routing_key=self.routing_key,
            body=body,
            properties=pika.BasicProperties(
                delivery_mode=2,
                content_type="application/json"
            )
        )
        command_connection.close()
    def supervise_agent(self, ch, method, properties, body):
        error_text = body.decode('utf-8')
        try:
            rollback_agent()
            start_agent()
            self.send_start_command(error_text)
            ch.basic_ack(delivery_tag=method.delivery_tag)
        except Exception as e:
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)