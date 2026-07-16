import logging
import pathlib
import sys
import threading

from client.core.rabbitmq_client import RabbitMQClient
from client.ui.console import ConsoleClientUI, read_login_payload

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

logger = logging.getLogger(__name__)


def main() -> None:
    ui = ConsoleClientUI()
    login, password, agent_type, agent_config = read_login_payload()
    client = RabbitMQClient(event_handler=ui)
    client.agent_session = {"agent_type": agent_type, "agent_config": agent_config}
    logger.info("Starting client")
    client.send_login(login, password)

    input_thread = threading.Thread(target=ui.input_loop, args=(client,), daemon=True)
    input_thread.start()
    try:
        client.start_consuming()
    except KeyboardInterrupt:
        print("\nClient stopped")
        sys.exit(0)


if __name__ == "__main__":
    main()
