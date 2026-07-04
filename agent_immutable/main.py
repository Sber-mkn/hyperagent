import logging
import sys
import traceback

from agent.main import agent_logic
from agent_immutable.rabbitmq.rabbitmq_agent import RabbitMQAgent

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    rabbitmq = RabbitMQAgent()
    rabbitmq.start_consuming()
    command, task, error, snapshot = rabbitmq.get_command()
    if command == "start":
        logger.info("Agent started")
        logger.info("Task: %s", task)
        try:
            agent_logic()
            rabbitmq.send_ack()
            sys.exit(0)
        except Exception:
            error_text = traceback.format_exc()
            rabbitmq.send_error(error_text)
            logger.exception(error_text)
            sys.exit(0)


