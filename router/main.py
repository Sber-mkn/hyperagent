import logging
import os
import sys

from router.rabbitmq.rabbitmq_router import RabbitMQRouter

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout
)
logger = logging.getLogger(__name__)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    logger.info("Starting RabbitMQ Router")

    logger.info(f"ROUTER_HOST: {os.getenv('ROUTER_HOST', 'NOT SET')}")
    logger.info(f"ROUTER_PORT: {os.getenv('ROUTER_PORT', 'NOT SET')}")
    logger.info(f"ROUTER_DB: {os.getenv('ROUTER_DB', 'NOT SET')}")
    logger.info(f"ROUTER_USER: {os.getenv('ROUTER_USER', 'NOT SET')}")
    logger.info(f"RABBITMQ_HOST: {os.getenv('RABBITMQ_HOST', 'NOT SET')}")
    logger.info(f"RABBITMQ_PORT: {os.getenv('RABBITMQ_PORT', 'NOT SET')}")

    try:
        rabbitmq = RabbitMQRouter()
        rabbitmq.start_consuming()
    except Exception as e:
        logger.exception(e)