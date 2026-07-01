import logging
import pathlib

from supervisor.rabbitmq_service.rabbitmq_supervisor import RabbitMQService
from supervisor.git_service.git_service import SupervisorGitService


logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    logger.info("Starting supervisor")
    try:
        rabbitmq = RabbitMQService()
        git_service = SupervisorGitService(rabbitmq)
        rabbitmq.send_start_command()
        rabbitmq.start_consuming()
    except Exception as e:
        logger.exception(e)
