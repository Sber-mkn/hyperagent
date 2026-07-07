import logging

from supervisor.git_service.git_service import GitService
from supervisor.rabbitmq.rabbitmq_supervisor import RabbitMQSupervisor

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    logger.info("Starting supervisor")
    try:
        git = GitService()
        rabbitmq = RabbitMQSupervisor(git)

        rabbitmq.send_ready_message()
        rabbitmq.start_consuming()
    except Exception as e:
        logger.exception(e)
