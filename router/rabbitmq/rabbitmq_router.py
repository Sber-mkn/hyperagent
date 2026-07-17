import json
import logging
import os
import threading

import bcrypt
import pika

from router.database.crud import add_user, get_user
from router.docker_manager import DockerManager

RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "router_rabbitmq")
RABBITMQ_PORT = os.getenv("RABBITMQ_PORT", 5672)
RABBITMQ_USER = os.getenv("RABBITMQ_USER", "router")
RABBITMQ_PASSWORD = os.getenv("RABBITMQ_PASSWORD", "12345")
RABBITMQ_URL = f"amqp://{RABBITMQ_USER}:{RABBITMQ_PASSWORD}@{RABBITMQ_HOST}:{RABBITMQ_PORT}/"
ROUTER_EXCHANGE = "router_exchange"
ROUTER_QUEUE = "router_queue"
LOGOUT_DELAY_SECONDS = int(os.getenv("ROUTER_LOGOUT_DELAY_SECONDS", "60"))

logger = logging.getLogger(__name__)


class RabbitMQRouter:
    def __init__(self, exchange=ROUTER_EXCHANGE, queue=ROUTER_QUEUE):
        self.connection = pika.BlockingConnection(pika.URLParameters(RABBITMQ_URL))
        self.channel = self.connection.channel()
        self.exchange = exchange
        self.queue = queue
        self.docker_manager = DockerManager()
        self.logout_timers = {}

    def start_consuming(self):
        self.channel.basic_qos(prefetch_count=1)
        self.channel.basic_consume(queue=self.queue, on_message_callback=self.receive_message)
        logger.info(f"Start consuming: {self.queue}")
        try:
            self.channel.start_consuming()
        except pika.exceptions.AMQPConnectionError:
            logger.exception("RabbitMQ connection failed")
            raise

    def receive_message(self, ch, method, properties, body):
        try:
            message = json.loads(body.decode("utf-8"))
            message_type = message.get("type")
            login = message.get("login")
            password = message.get("password")
            if message_type == "login" and login and password:
                self._cancel_logout(login)
                user = get_user(login)
                if not user:
                    password_hash = bcrypt.hashpw(
                        password.encode("utf-8"), bcrypt.gensalt()
                    ).decode("utf-8")
                    client_data = self.docker_manager.start_client(login=login)
                    add_user(
                        login=login,
                        password_hash=password_hash,
                        db_port=client_data["db_port"],
                        rabbitmq_port=client_data["rabbitmq_port"],
                        rabbitmq_mgmt_port=client_data["rabbitmq_mgmt_port"],
                    )
                    user = get_user(login)
                else:
                    if not bcrypt.checkpw(
                        password.encode("utf-8"), user.password_hash.encode("utf-8")
                    ):
                        self.send_error(ch, properties, "Invalid login or password")
                        ch.basic_ack(delivery_tag=method.delivery_tag)
                        return

                    self.docker_manager.restart_client(
                        login=login,
                        db_port=user.db_port,
                        rabbitmq_port=user.rabbitmq_port,
                        rabbitmq_mgmt_port=user.rabbitmq_mgmt_port,
                    )

                logger.info(user.rabbitmq_port)
                credentials = {
                    "type": "login_response",
                    "rabbitmq_host": os.getenv("SERVER_EXTERNAL_IP", "localhost"),
                    "rabbitmq_port": user.rabbitmq_port,
                    "rabbitmq_user": "client",
                    "rabbitmq_password": "12345",
                    "login": login,
                }
                self.send_response(ch, properties, credentials)
            elif message_type == "logout":
                login = message.get("login")
                self._schedule_logout(login)
            ch.basic_ack(delivery_tag=method.delivery_tag)

        except Exception:
            logger.exception("Error processing message")
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)

    def send_response(self, ch, properties, response: dict):
        ch.basic_publish(
            exchange="",
            routing_key=properties.reply_to,
            body=json.dumps(response),
            properties=pika.BasicProperties(
                correlation_id=properties.correlation_id, content_type="application/json"
            ),
        )

    def send_error(self, ch, properties, error_text: str):
        self.send_response(ch, properties, {"status": "error", "error": error_text})

    def _cancel_logout(self, login: str):
        timer = self.logout_timers.pop(login, None)
        if timer:
            timer.cancel()

    def _schedule_logout(self, login: str):
        if not login:
            return
        self._cancel_logout(login)
        if LOGOUT_DELAY_SECONDS <= 0:
            self.docker_manager.stop_client(login)
            return
        timer = threading.Timer(
            LOGOUT_DELAY_SECONDS, self.docker_manager.stop_client, args=(login,)
        )
        timer.daemon = True
        self.logout_timers[login] = timer
        timer.start()
