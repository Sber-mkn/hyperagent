import json
import logging

import pika
from pika import exceptions

from contracts.git_commands import (
    GitAddPathsCommand,
    GitCommitCommand,
    GitDiffCommand,
    GitRollbackCommand,
    GitStagedDiffCommand,
    GitStatusCommand,
)
from contracts.requests import GitRequest
from supervisor.git_service.git_service import AgentGitService
from supervisor.message_handler import ack_handler, commit_handler, error_handler

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
        self.git_service = AgentGitService(self)
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
        logger.info(f"Message published: {message.get('command')}")
        self.channel.basic_publish(
            exchange=self.exchange,
            routing_key=self.routing_key,
            body=body,
            properties=pika.BasicProperties(delivery_mode=2, content_type="application/json"),
        )

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
                request = GitRequest.model_validate(message)
                command = request.command
                if isinstance(command, GitStatusCommand):
                    self.git_service.status()
                elif isinstance(command, GitDiffCommand):
                    self.git_service.diff()
                elif isinstance(command, GitStagedDiffCommand):
                    self.git_service.staged_diff()
                elif isinstance(command, GitAddPathsCommand):
                    self.git_service.add_paths(command.paths)
                elif isinstance(command, GitCommitCommand):
                    self.git_service.commit(command.message, paths=command.paths)
                elif isinstance(command, GitRollbackCommand):
                    self.git_service.rollback(command.target_sha)
                ch.basic_ack(delivery_tag=method.delivery_tag)

            elif message_type == "commit":
                commit_handler(message)
                self.send_start_command(snapshot_text=message.get("snapshot_text"))
                ch.basic_ack(delivery_tag=method.delivery_tag)

            elif message_type == "error":
                error_text = message.get("error")
                snapshot_sha, snapshot_text = error_handler(message)
                self.git_service.rollback(snapshot_sha)
                self.send_stop_command()
                self.send_start_command(error_text, snapshot_text)
                ch.basic_ack(delivery_tag=method.delivery_tag)

            elif message_type == "ack":
                ack_handler()
                ch.basic_ack(delivery_tag=method.delivery_tag)

            else:
                logger.info(f"Unknown type: {message_type}")
                ch.basic_ack(delivery_tag=method.delivery_tag)

        except Exception as e:
            logger.exception(f"Message error: {e}")
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)
