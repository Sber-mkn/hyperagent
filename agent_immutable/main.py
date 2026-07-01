import logging
import sys
import traceback

from agent.main import test_logic
from agent_immutable.git_service.git_check import git_check
from agent_immutable.rabbitmq.rabbitmq_agent import RabbitMQService

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    rabbitmq = RabbitMQService()
    rabbitmq.start_consuming()
    command, error, snapshot = rabbitmq.get_command()
    if error:
        logger.info("Agent started after rollback")
        test_logic()
        sys.exit(0)
    elif command == "start":
        logger.info("Agent started")
        sha = git_check()
        if not sha:
            try:
                test_logic()
                rabbitmq.send_ack()
                sys.exit(0)
            except Exception:
                error_text = traceback.format_exc()
                rabbitmq.send_error(error_text)
                logger.exception(error_text)
                sys.exit(0)
        else:
            rabbitmq.send_commit(sha, "Unknown")
    elif command == "stop":
        logger.info("Agent stopped")
        sys.exit(0)


