import docker

from database.crud import get_snapshot_by_status

AGENT_REPO = "/agent"
AGENT_CONTAINER = "hyperagent_agent"

docker_client = docker.from_env()


def start_agent():
    agent_container = docker_client.containers.get(AGENT_CONTAINER)
    if agent_container.status == "exited":
        agent_container.start()
    elif agent_container.status == "running":
        agent_container.restart()
