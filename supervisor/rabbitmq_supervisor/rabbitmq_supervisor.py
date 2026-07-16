import json
import logging

from rabbitmq.rabbitmq_service import RabbitMQBase
from supervisor.message_handler import ack_handler, client_data_handler, error_handler, git_handler
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
        self.agent_ready = True
        logger.info("RabbitMQ connection established")

    def send_start_command(
        self,
        task=None,
        error_text=None,
        agent_session=None,
        replayed_task=False,
    ):
        message = {
            "command": "start",
        }
        if task:
            message["task"] = task
        if error_text:
            message["error_text"] = error_text
        if agent_session is not None:
            message["agent_session"] = agent_session
        if replayed_task:
            message["replayed_task"] = True
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

            if message.get("command") == "start":
                self.send_start_command(
                    task=message.get("task"),
                    agent_session=message.get("agent_session"),
                )

            elif message_type == "client_data":
                result = client_data_handler(message)
                self.send_response(
                    reply_to=properties.reply_to,
                    correlation_id=properties.correlation_id,
                    response=result,
                )

            elif message_type == "git":
                result = git_handler(message, self.git_service)

                if result.get("restart_agent"):
                    self.agent_ready = False
                    self.publish_message(
                        {
                            "type": "agent_message",
                            "message_type": "status",
                            "message": (
                                "Версия сохранена, инструменты обновлены. Перезапускаю агента, "
                                "чтобы применить изменения — это займёт несколько секунд..."
                            ),
                        },
                        CLIENT_KEY,
                    )
                    start_agent()

                    self.send_start_command(
                        task=message.get("task"),
                        agent_session=message.get("agent_session"),
                        replayed_task=True,
                    )
                else:
                    self.send_response(
                        reply_to=properties.reply_to,
                        correlation_id=properties.correlation_id,
                        response=result,
                    )

            elif message_type == "error":
                self.agent_ready = False
                error_text = error_handler(message, self.git_service)
                self.send_start_command(
                    task=message.get("task"),
                    error_text=error_text,
                    agent_session=message.get("agent_session"),
                    replayed_task=True,
                )

            elif message_type == "ack":
                ack_handler(self.git_service)
                self.agent_ready = True
                self.send_ready_message()

            elif message_type == "login":
                if self.agent_ready:
                    self.send_ready_message()
                else:
                    self.publish_message(
                        {
                            "type": "agent_message",
                            "message_type": "status",
                            "message": "Agent is starting, wait for ready.",
                        },
                        CLIENT_KEY,
                    )

            else:
                logger.info(f"Unknown type: {message_type}")

            ch.basic_ack(delivery_tag=method.delivery_tag)

        except Exception as e:
            logger.exception(f"Message error: {e}")
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)
