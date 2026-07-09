import logging
import sys
import traceback

from agent.main import agent_logic
from agent_immutable.on_functions import on_command, on_content, on_end_message, on_think
from agent_immutable.rabbitmq import RabbitMQAgent
from agent_immutable.runtime import set_rabbitmq

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    rabbitmq = RabbitMQAgent()
    set_rabbitmq(rabbitmq)
    rabbitmq.start_consuming()

    command, task, error, llm_chat = rabbitmq.get_command()

    if command == "start":
        logger.info("Agent started")
        logger.info("Task: %s", task)
        try:
            agent_logic(
                task=task or "",
                error_text=error,
                llm_chat=llm_chat,
                on_think=on_think,
                on_content=on_content,
                on_end_message=on_end_message,
                on_command=on_command,
            )
            rabbitmq.send_ack()

        except Exception:
            error_text = traceback.format_exc()
            rabbitmq.send_error(error_text, task)
            logger.exception(error_text)
            sys.exit(0)
