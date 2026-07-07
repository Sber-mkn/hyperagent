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
from supervisor.git_service.git_service import AgentGitService
from supervisor.message_handler import ack_handler, commit_handler, error_handler

logger = logging.getLogger(__name__)

USER = "supervisor"
PASSWORD = "12345"
EXCHANGE = "agent_exchange"
QUEUE = "supervisor_queue"
ROUTING_KEY = "agent"
CLIENT_KEY = "client"


class RabbitMQSupervisor(RabbitMQBase):
    def __init__(self, user = USER, password = PASSWORD, exchange=EXCHANGE,
                queue=QUEUE, routing_key=ROUTING_KEY):
        super().__init__(user, password, exchange, queue, routing_key)
        self.git_service = AgentGitService(self)
        logger.info("RabbitMQ connection established")

    def send_start_command(self, task=None, error_text=None, snapshot_text=None):
        message = {
            "command": "start",
        }
        if task:
            message["task"]=task
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
                task = message.get("task")
                snapshot_sha, snapshot_text = error_handler(message)
                if snapshot_sha:
                    self.send_start_command(task, error_text, snapshot_text)
                ch.basic_ack(delivery_tag=method.delivery_tag)

            elif message_type == "ack":
                ack_handler()
                self.send_ready_message()
                ch.basic_ack(delivery_tag=method.delivery_tag)

            else:
                logger.info(f"Unknown type: {message_type}")
                ch.basic_ack(delivery_tag=method.delivery_tag)

        except Exception as e:
            logger.exception(f"Message error: {e}")
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)
