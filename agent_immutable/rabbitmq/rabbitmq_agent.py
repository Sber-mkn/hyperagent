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
        self.snapshot_text = None
        self.task = None

    def receive_message(self, ch, method, properties, body):
        try:
            message = json.loads(body.decode("utf-8"))
            logger.info(f"Received message: {message.get('type')}")
            self.task = message.get("task")
            self.command = message.get("command", "")
            self.error_text = message.get("error_text", None)
            self.snapshot_text = message.get("snapshot_text", None)
            ch.basic_ack(delivery_tag=method.delivery_tag)
            ch.stop_consuming()
        except Exception as e:
            logger.exception(f"Error processing command: {e}")
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)

    def send_commit(self, commit_text):
        message = {"type": "commit", "commit_text": commit_text}
        self.publish_message(message)

    def send_error(self, error_text, task):
        message = {"type": "error", "error": error_text, "task": task}
        logger.info("Send error: %s", message)
        self.publish_message(message)

    def send_result(self, result_json):
        result_dict = json.loads(result_json)
        client_block = result_dict.get("client", result_dict)
        message = {
            "type": "result",
            "status": client_block.get("status"),
            "summary": client_block.get("summary"),
            "answer": client_block.get("answer"),
            "artifacts": client_block.get("artifacts"),
            "metrics": result_dict.get("metrics"),
        }
        logger.info("Send result to client (status=%s)", message.get("status"))
        self.publish_message(message, "client")

    def send_ack(self):
        message = {"type": "ack"}
        logger.info("Send ack")
        self.publish_message(message)

    def get_command(self):
        return self.command, self.task, self.error_text, self.snapshot_text
