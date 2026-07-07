import json
import logging

from contracts.git_commands import (
    GitAddPathsCommand,
    GitCommitCommand,
    GitDiffCommand,
    GitRollbackCommand,
    GitStagedDiffCommand,
    GitStatusCommand,
)
from contracts.requests import GitRequest
from rabbitmq.rabbitmq_service import RabbitMQBase
from supervisor.git_service.git_service import GitService
from supervisor.message_handler import ack_handler, error_handler, git_handler

logger = logging.getLogger(__name__)

USER = "supervisor"
PASSWORD = "12345"
EXCHANGE = "agent_exchange"
QUEUE = "supervisor_queue"
ROUTING_KEY = "agent"
CLIENT_KEY = "client"


class RabbitMQSupervisor(RabbitMQBase):
    def __init__(
        self,
        git_service: GitService,
        user=USER,
        password=PASSWORD,
        exchange=EXCHANGE,
        queue=QUEUE,
        routing_key=ROUTING_KEY,
    ):
        super().__init__(user, password, exchange, queue, routing_key)
        self.git_service = git_service
        logger.info("RabbitMQ connection established")

    def send_start_command(self, error_text=None, snapshot_text=None):
        message = {
            "command": "start",
        }
        if error_text:
            message["error_text"] = error_text
        if snapshot_text:
            message["snapshot_text"] = snapshot_text
        self.publish_message(message)

    def send_ready_message(self):
        message = {
            "command": "start",
            "type": "ready",
        }
        self.publish_message(message, CLIENT_KEY)

    def receive_message(self, ch, method, properties, body):
        try:
            message = json.loads(body.decode("utf-8"))
            message_type = message.get("type")
            logger.info(f"Message consumed: {message_type}")
            if message_type == "git":
                git_handler(message, self.git_service)
                ch.basic_ack(delivery_tag=method.delivery_tag)

            elif message_type == "error":
                error_text = message.get("error")
                snapshot_text = error_handler(message)
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
