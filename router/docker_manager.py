import logging
import os
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

ROOT_DIR = Path(os.getenv("BASE_DIR", "hyperagent"))
COMPOSE_FILE = "docker-compose.yml"


class DockerManager:
    def __init__(self):
        logger.info("DockerManager initialized")

    def start_client(self, login: str):
        port_hash = abs(hash(login)) % 10000
        db_port = 15432 + port_hash
        rabbitmq_port = 15672 + port_hash
        rabbitmq_mgmt_port = 25672 + port_hash
        self._run_compose(login, db_port, rabbitmq_port, rabbitmq_mgmt_port, build=True)
        return {
            "db_port": db_port,
            "rabbitmq_port": rabbitmq_port,
            "rabbitmq_mgmt_port": rabbitmq_mgmt_port,
        }

    def restart_client(
        self, login: str, db_port: int, rabbitmq_port: int, rabbitmq_mgmt_port: int
    ) -> dict:
        logger.info(
            f"Restarting EXISTING infrastructure for {login} with ports: DB={db_port}, RMQ={rabbitmq_port}"
        )
        self._run_compose(login, db_port, rabbitmq_port, rabbitmq_mgmt_port, build=False)
        return {
            "db_port": db_port,
            "rabbitmq_port": rabbitmq_port,
            "rabbitmq_mgmt_port": rabbitmq_mgmt_port,
        }

    def _run_compose(
        self, login: str, db_port: int, rabbitmq_port: int, rabbitmq_mgmt_port: int, build: bool
    ):
        env = os.environ.copy()
        env.update(
            {
                "LOGIN": login,
                "DB_PORT": str(db_port),
                "RABBITMQ_PORT": str(rabbitmq_port),
                "RABBITMQ_MGMT_PORT": str(rabbitmq_mgmt_port),
            }
        )
        command = [
            "docker",
            "compose",
            "-f",
            str(COMPOSE_FILE),
            "-p",
            f"{login}",
            "--profile",
            "agent",
            "up",
            "-d",
        ]
        if build:
            command.append("--build")

        try:
            result = subprocess.run(
                command, cwd=ROOT_DIR, capture_output=True, text=True, env=env, timeout=300
            )

            if result.returncode != 0:
                logger.error(f"Docker compose failed for {login}")
                logger.error(f"STDOUT - \n{result.stdout}")
                logger.error(f"STDERR -\n{result.stderr}")
            else:
                logger.info(f"Docker compose succeeded for {login}")

        except subprocess.TimeoutExpired:
            logger.error(f"Docker compose timed out for {login}")
        except Exception as e:
            logger.exception(f"Error running docker compose for {login}: {e}")

    def stop_client(self, login: str):
        logger.info(f"Stopping agent for {login}")
        command = [
            "docker",
            "compose",
            "-f",
            str(COMPOSE_FILE),
            "-p",
            f"{login}",
            "--profile",
            "agent",
            "down",
        ]

        result = subprocess.run(command, cwd=ROOT_DIR, capture_output=True, text=True)
        if result.returncode == 0:
            logger.info(f"Successfully stopped infrastructure for {login}")
        else:
            logger.warning(f"Failed to stop infrastructure for {login}")
