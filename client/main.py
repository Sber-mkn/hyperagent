import logging
import sys
import threading

logger = logging.getLogger(__name__)

from client.rabbitmq.rabbitmq_client import RabbitMQClient

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    client = RabbitMQClient()
    logger.info("Starting client")

    input_thread = threading.Thread(target=client.input_loop, daemon=True)
    input_thread.start()
    try:
        client.start_consuming()
    except KeyboardInterrupt:
        print("\nClient stopped")
        sys.exit(0)
