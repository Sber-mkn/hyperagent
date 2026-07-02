import logging
import sys
import traceback

from agent.main import test_logic
from agent_immutable.rabbitmq.rabbitmq_agent import RabbitMQService

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    rabbitmq = RabbitMQService()
    rabbitmq.start_consuming()
    command, error, snapshot = rabbitmq.get_command()
    if command == "start":
        logger.info("Agent started")
        try:
            test_logic()
            rabbitmq.send_ack()
            sys.exit(0)
        except Exception:
            error_text = traceback.format_exc()
            rabbitmq.send_error(error_text)
            logger.exception(error_text)
            sys.exit(0)
    elif command == "stop":
        logger.info("Agent stopped")
        sys.exit(0)


