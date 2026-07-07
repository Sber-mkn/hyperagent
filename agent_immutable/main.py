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
            result_json = agent_logic(
                task or "",
                error_text=error,
                snapshot_text=snapshot,
            )
            logger.info("Agent result: %s", result_json[:500])
            rabbitmq.send_result(result_json)
            rabbitmq.send_ack()
            sys.exit(0)
        except Exception as exc:
            error_text = traceback.format_exc()
            rabbitmq.send_error(error_text, task)
            logger.exception(error_text)
            sys.exit(0)


