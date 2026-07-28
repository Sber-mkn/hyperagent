import json
import logging

from rabbitmq.rabbitmq_service import RabbitMQBase
from supervisor.message_handler import (
    ack_handler,
    client_data_handler,
    error_handler,
    failure_summary,
    git_handler,
)
from supervisor.rollback import agent_container_running, start_agent

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
                outcome = error_handler(message, self.git_service)
                self.agent_ready = True

                if outcome["rolled_back"]:
                    # The source was restored underneath the task, so running it
                    # again is a genuinely different attempt.
                    self.send_start_command(
                        task=message.get("task"),
                        error_text=outcome["error_text"],
                        agent_session=message.get("agent_session"),
                        replayed_task=True,
                    )
                else:
                    # Same code, same task, same outcome — replaying it just
                    # loops. Tell the person instead of retrying in silence.
                    self.publish_message(
                        {
                            "type": "error",
                            "error": f"Задача не выполнена: "
                            f"{failure_summary(outcome['error_text'])}",
                        },
                        CLIENT_KEY,
                    )
                    self.send_ready_message()

            elif message_type == "ack":
                ack_handler(self.git_service)
                self.agent_ready = True
                self.send_ready_message()

            elif message_type == "login":
                # agent_ready only ever came back on ack, i.e. after a task
                # finished. A crashed or rolled-back agent left it stuck at
                # False, and since the client cannot send a task until it sees
                # ready, nothing could ever clear it again — every later login
                # hung until the container was recreated. Docker knows the real
                # state, so ask it instead of trusting the last event seen.
                if not self.agent_ready:
                    self.agent_ready = agent_container_running()
                if self.agent_ready:
                    logger.info("Login: agent is ready")
                    self.send_ready_message()
                else:
                    logger.info("Login: agent is not running yet")
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
            # Never requeue: a message that made the handler raise will do it
            # again on redelivery, and with prefetch=1 that single message
            # loops forever and blocks every other client request behind it —
            # one unreachable model address was enough to wedge the supervisor
            # entirely. Answer the caller instead of leaving it to time out.
            reply_to = getattr(properties, "reply_to", None)
            if reply_to:
                self.send_response(
                    reply_to=reply_to,
                    correlation_id=getattr(properties, "correlation_id", None),
                    response={"error": " ".join(str(e).split())[:300] or type(e).__name__},
                )
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
