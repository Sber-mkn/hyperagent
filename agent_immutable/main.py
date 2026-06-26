import traceback
import sys

from agent.main import test_logic
from agent_immutable.rabbitmq.rabbitmq_agent import RabbitMQServise

AGENT_ERROR_LOG = "/logs/agent_error.log"

if __name__ == "__main__":
    rabbitmq = RabbitMQServise()
    rabbitmq.start_consuming()
    command, error, snapshot = rabbitmq.get_command()
    if command == "start":
        try:
            test_logic()
        except Exception as e:
            error_text = traceback.format_exc()
            rabbitmq.send_error(error_text)
            sys.exit(1)

