import json
import logging
import threading

import pika

from rabbitmq.rabbitmq_service import RabbitMQBase

USER = "client"
PASSWORD = "12345"
EXCHANGE = "agent_exchange"
CLIENT_QUEUE = "client_queue"
ROUTING_KEY = "agent"

logger = logging.getLogger(__name__)

class RabbitMQClient(RabbitMQBase):
    def __init__(self, user=USER, password = PASSWORD, exchange=EXCHANGE,
                 queue=CLIENT_QUEUE, routing_key=ROUTING_KEY):
        super().__init__(user,password,exchange, queue, routing_key)
        self.is_ready = False
        self.pending_message = None
        self.ready_event = threading.Event()

    def receive_message(self, ch, method, properties, body):
        try:
            message = json.loads(body.decode("utf-8"))
            message_type = message.get("type")
            logger.info(f"Received message: {message_type}")
            if message_type == "ready":
                self.is_ready = True
                self.ready_event.set()
                print("\nHyperagent is READY\n")
                ch.basic_ack(delivery_tag=method.delivery_tag)

            elif message_type == "result":
                print(f"\nResult received")
                print(f"Status: {message.get('status')}")
                print(f"Answer: {message.get('answer')}")
                print(f"Artifacts: {message.get('artifacts')}")
                self.is_ready = False
                ch.basic_ack(delivery_tag=method.delivery_tag)

            else:
                logger.warning(f"Unknown message type: {message_type}")
                ch.basic_ack(delivery_tag=method.delivery_tag)

        except Exception as e:
            logger.exception(f"Error processing message: {e}")
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)

        except Exception as e:
            logger.exception(f"Error processing message: {e}")
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
                user_input = input("Enter your request: ").strip()
                user_input = user_input.encode('utf-8', errors='replace').decode('utf-8')
            except EOFError:
                print("\nStdin closed, exiting")
                break

            if not user_input:
                continue
            message = {
                "task": user_input,
                "command": "start"
            }
            self.pending_message = message
            self.connection.add_callback_threadsafe(self.publish)