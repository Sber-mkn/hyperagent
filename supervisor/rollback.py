import docker

from database.crud import get_snapshot_by_status

AGENT_REPO = "/agent"
AGENT_CONTAINER = "hyperagent_agent"

docker_client = docker.from_env()


def rollback_agent():
    snapshot = get_snapshot_by_status("STABLE")
    if not snapshot:
        raise ValueError("Database has not STABLE snapshot")
    _, snapshot_sha, snapshot_text = snapshot


def start_agent():
    agent_container = docker_client.containers.get(AGENT_CONTAINER)
    if agent_container.status == "exited":
        agent_container.start()
    elif agent_container.status == "running":
        agent_container.restart()
