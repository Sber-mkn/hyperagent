import json
import logging

from database.agent.crud import get_llmchat
from rabbitmq.rabbitmq_service import RabbitMQBase
from supervisor.message_handler import ack_handler, error_handler, git_handler
from supervisor.rollback import start_agent

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
        git_service,
        user=USER,
        password=PASSWORD,
        exchange=EXCHANGE,
        queue=QUEUE,
        routing_key=ROUTING_KEY,
    ):
        super().__init__(user, password, exchange, queue, routing_key)
        self.git_service = git_service
        logger.info("RabbitMQ connection established")

    def send_start_command(self, task=None, error_text=None, llm_chat=None):
        message = {
            "command": "start",
        }
        if task:
            message["task"] = task
        if error_text:
            message["error_text"] = error_text
        if llm_chat is not None:
            message["llm_chat"] = llm_chat
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
            logger.info("Message consumed: %s", message_type)

            if message_type == "git":
                result = git_handler(message, self.git_service)

                if result.get("restart_agent"):
                    start_agent()
                    self.send_start_command(llm_chat=get_llmchat())
                else:
                    self.send_response(
                        reply_to=properties.reply_to,
                        correlation_id=properties.correlation_id,
                        response=result,
                    )

            elif message_type == "error":
                error_text = error_handler(message, self.git_service)
                self.send_start_command(
                    task=message.get("task"),
                    error_text=error_text,
                    llm_chat=get_llmchat(),
                )

            elif message_type == "ack":
                ack_handler(self.git_service)
                self.send_ready_message()

            else:
                logger.info(f"Unknown type: {message_type}")

            ch.basic_ack(delivery_tag=method.delivery_tag)

        except Exception as e:
            logger.exception(f"Message error: {e}")
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)
