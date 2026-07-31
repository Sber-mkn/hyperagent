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
        self._client_locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

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
        """Acknowledge and hand the work to a thread straight away.

        Starting a user's stack takes anywhere from seconds to minutes. Doing
        that inside this callback blocked pika's I/O loop for the whole time, so
        the broker saw no heartbeats and reset the connection; the reply then
        failed, the error path tried to nack on the dead channel, and the router
        died. Its unacknowledged message was redelivered on restart, launching
        compose a second time over the first. Answering off the I/O thread also
        means one user's slow first login no longer blocks everyone else's.
        """
        self._safe_ack(ch, method)
        try:
            message = json.loads(body.decode("utf-8"))
        except UnicodeDecodeError, json.JSONDecodeError:
            logger.exception("Malformed message dropped")
            return

        threading.Thread(
            target=self._handle_message,
            args=(message, properties.reply_to, properties.correlation_id),
            daemon=True,
        ).start()

    def _handle_message(self, message: dict, reply_to: str | None, correlation_id: str | None):
        message_type = message.get("type")
        login = message.get("login")
        try:
            if message_type == "login" and login and message.get("password"):
                self._handle_login(login, message["password"], reply_to, correlation_id)
            elif message_type == "logout":
                self._schedule_logout(login)
            else:
                logger.info("Ignoring message: type=%s", message_type)
        except Exception:
            logger.exception("Error processing %s for %s", message_type, login)
            self.send_error(reply_to, correlation_id, "Server error, try again")

    def _handle_login(
        self,
        login: str,
        password: str,
        reply_to: str | None,
        correlation_id: str | None,
    ):
        self._cancel_logout(login)

        with self._client_lock(login):
            user = get_user(login)
            if not user:
                logger.info("Login: creating account %s", login)
                password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode(
                    "utf-8"
                )
                client_data = self.docker_manager.start_client(login=login)
                add_user(
                    login=login,
                    password_hash=password_hash,
                    db_port=client_data["db_port"],
                    rabbitmq_port=client_data["rabbitmq_port"],
                    rabbitmq_mgmt_port=client_data["rabbitmq_mgmt_port"],
                )
                user = get_user(login)
            elif not bcrypt.checkpw(password.encode("utf-8"), user.password_hash.encode("utf-8")):
                logger.info("Login rejected for %s: wrong password", login)
                self.send_error(reply_to, correlation_id, "Invalid login or password")
                return
            else:
                self.docker_manager.restart_client(
                    login=login,
                    db_port=user.db_port,
                    rabbitmq_port=user.rabbitmq_port,
                    rabbitmq_mgmt_port=user.rabbitmq_mgmt_port,
                )

        logger.info("Login accepted for %s, personal RabbitMQ port %s", login, user.rabbitmq_port)
        credentials = {
            "type": "login_response",
            "rabbitmq_port": user.rabbitmq_port,
            "rabbitmq_user": "client",
            "rabbitmq_password": "12345",
            "login": login,
        }
        external_host = os.getenv("SERVER_EXTERNAL_IP", "").strip()
        if external_host:
            credentials["rabbitmq_host"] = external_host
        self.send_response(reply_to, correlation_id, credentials)

    def send_response(self, reply_to: str | None, correlation_id: str | None, response: dict):
        """Publishing must happen on the thread that owns the connection, so the
        worker hands it back to pika's I/O loop rather than touching the channel."""
        if not reply_to:
            return
        self.connection.add_callback_threadsafe(
            lambda: self._publish_response(reply_to, correlation_id, response)
        )

    def send_error(self, reply_to: str | None, correlation_id: str | None, error_text: str):
        self.send_response(reply_to, correlation_id, {"status": "error", "error": error_text})

    def _publish_response(self, reply_to: str, correlation_id: str | None, response: dict):
        try:
            self.channel.basic_publish(
                exchange="",
                routing_key=reply_to,
                body=json.dumps(response),
                properties=pika.BasicProperties(
                    correlation_id=correlation_id, content_type="application/json"
                ),
            )
        except Exception:
            logger.exception("Failed to deliver reply to %s", reply_to)

    @staticmethod
    def _safe_ack(ch, method):
        try:
            ch.basic_ack(delivery_tag=method.delivery_tag)
        except Exception:
            logger.exception("Could not acknowledge message")

    def _client_lock(self, login: str) -> threading.Lock:
        with self._locks_guard:
            return self._client_locks.setdefault(login, threading.Lock())

    def _cancel_logout(self, login: str):
        timer = self.logout_timers.pop(login, None)
        if timer:
            timer.cancel()

    def _stop_client(self, login: str):
        with self._client_lock(login):
            self.docker_manager.stop_client(login)

    def _schedule_logout(self, login: str):
        if not login:
            return
        self._cancel_logout(login)
        if LOGOUT_DELAY_SECONDS <= 0:
            self._stop_client(login)
            return
        timer = threading.Timer(LOGOUT_DELAY_SECONDS, self._stop_client, args=(login,))
        timer.daemon = True
        self.logout_timers[login] = timer
        timer.start()
