import logging
import sys
import traceback

from agent.tools import registry
from agent.main import agent_logic
from agent_immutable.on_functions import (
    on_command,
    on_content,
    on_end_message,
    on_error,
    on_l3,
    on_start_message,
    on_think,
    on_title,
    on_tool_call,
)
from agent_immutable.rabbitmq_agent import RabbitMQAgent
from agent_immutable.runtime import set_rabbitmq

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    rabbitmq = RabbitMQAgent()
    set_rabbitmq(rabbitmq)
    registry.on_command = on_command
    registry.running_on_server = True
    rabbitmq.start_consuming()

    command, task, error, llm_chat, l3_memory, agent_session = rabbitmq.get_command()

    if command == "start":
        logger.info("Agent started")
        logger.info("Task: %s", task)
        try:
            agent_logic(
                user_message=task,
                error_text=error,
                on_think=on_think,
                on_content=on_content,
                on_title=on_title,
                on_tool=on_command,
                on_tool_call=on_tool_call,
                on_error=on_error,
                on_end_message=on_end_message,
                on_l3=on_l3,
                on_start_message=on_start_message,
                llm_chat=llm_chat,
                l3_memory=l3_memory,
                agent_session=agent_session,
            )
            rabbitmq.send_ack()

        except Exception:
            error_text = traceback.format_exc()
            rabbitmq.send_error(error_text, task)
            logger.exception(error_text)
            sys.exit(0)
