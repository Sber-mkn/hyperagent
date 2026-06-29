import sys
import traceback

from agent.main import test_logic
from agent_immutable.rabbitmq.rabbitmq_agent import RabbitMQService

if __name__ == "__main__":
    print("Starting agent")
    rabbitmq = RabbitMQService()
    rabbitmq.start_consuming()
    command, error, snapshot = rabbitmq.get_command()
    if command == "start":
        try:
            test_logic()
        except Exception:
            error_text = traceback.format_exc()
            rabbitmq.send_error(error_text)
            sys.exit(1)
    if command == "stop":
        print("Agent stopped")
