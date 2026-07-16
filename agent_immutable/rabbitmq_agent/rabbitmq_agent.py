import json
import logging

from database.agent.crud import get_l3_memory, get_llmchat
from rabbitmq.rabbitmq_service import RabbitMQBase

logger = logging.getLogger(__name__)

USER = "agent"
PASSWORD = "12345"
EXCHANGE = "agent_exchange"
AGENT_QUEUE = "agent_queue"
ROUTING_KEY = "supervisor"


class RabbitMQAgent(RabbitMQBase):
    def __init__(
        self,
        user=USER,
        password=PASSWORD,
        exchange=EXCHANGE,
        queue=AGENT_QUEUE,
        routing_key=ROUTING_KEY,
    ):
        super().__init__(user, password, exchange, queue, routing_key)
        self.command = None
        self.error_text = None
        self.llm_chat = []
        self.l3_memory = None
        self.task = None
        self.agent_session = {}
        self.chat_id = None
        self.replayed_task = False

    @staticmethod
    def _agent_session_from_message(message: dict) -> dict:
        session = message.get("agent_session")
        return {
            "agent_type": session.get("agent_type"),
            "agent_config": session.get("agent_config"),
            "chat_id": session.get("chat_id"),
        }

    def receive_message(self, ch, method, properties, body):
        try:
            message = json.loads(body.decode("utf-8"))
            logger.info(f"Received message: {message.get('type')}")
            self.task = message.get("task")
            self.command = message.get("command", "")
            self.error_text = message.get("error_text", None)
            self.replayed_task = bool(message.get("replayed_task"))
            self.agent_session = self._agent_session_from_message(message)
            self.chat_id = self.agent_session.get("chat_id")
            self.llm_chat = get_llmchat(self.chat_id)
            self.l3_memory = get_l3_memory(self.chat_id)
            ch.basic_ack(delivery_tag=method.delivery_tag)
            ch.stop_consuming()

        except Exception as e:
            logger.exception(f"Error processing command: {e}")
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)

    def send_error(self, error_text, task=None):
        message = {"type": "error", "error": error_text, "agent_session": self.agent_session}
        if task is not None:
            message["task"] = task
        logger.info("Send error: %s", message)
        self.publish_message(message)

    def send_result(self, result_json):
        message = {
            "type": "result",
            "status": result_json.get("status"),
            "summary": result_json.get("summary"),
            "answer": result_json.get("answer"),
            "artifacts": result_json.get("artifacts"),
            "metrics": result_json.get("metrics"),
        }
        self.publish_message(message, "client")

    def send_ack(self):
        message = {"type": "ack"}
        logger.info("Send ack")
        self.publish_message(message)

    def get_command(self):
        return (
            self.command,
            self.task,
            self.error_text,
            self.llm_chat,
            self.l3_memory,
            self.agent_session,
        )
