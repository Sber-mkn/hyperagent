import logging
import sys
import threading

from client.rabbitmq_client.rabbitmq_client import RabbitMQClient

logger = logging.getLogger(__name__)

if __name__ == "__main__":
    client = RabbitMQClient()
    logger.info("Starting client")

    input_thread = threading.Thread(target=client.input_loop, daemon=True)
    input_thread.start()
    try:
        client.start_consuming()
    except KeyboardInterrupt:
        print("\nClient stopped")
        sys.exit(0)
