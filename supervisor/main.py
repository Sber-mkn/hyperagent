import logging

from supervisor.rabbitmq_service.rabbitmq_supervisor import RabbitMQService

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    logger.info("Starting supervisor")
    try:
        rabbitmq = RabbitMQService()
        rabbitmq.send_start_command()
        rabbitmq.start_consuming()
    except Exception as e:
        logger.exception(e)
