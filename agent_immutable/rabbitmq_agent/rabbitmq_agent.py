import json
import logging

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
        self.task = None

    def receive_message(self, ch, method, properties, body):
        try:
            message = json.loads(body.decode("utf-8"))
            logger.info(f"Received message: {message.get('type')}")
            self.task = message.get("task")
            self.command = message.get("command", "")
            self.error_text = message.get("error_text", None)
            self.llm_chat = message.get("llm_chat", [])
            ch.basic_ack(delivery_tag=method.delivery_tag)
            ch.stop_consuming()

        except Exception as e:
            logger.exception(f"Error processing command: {e}")
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)

    def send_error(self, error_text, task=None):
        message = {"type": "error", "error": error_text}
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
        return self.command, self.task, self.error_text, self.llm_chat
