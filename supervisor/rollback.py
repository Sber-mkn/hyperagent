import os

import docker

AGENT_REPO = "/agent"
AGENT_CONTAINER = os.getenv(
    "AGENT_CONTAINER_NAME", f"hyperagent_agent_{os.getenv('LOGIN', 'unknown')}"
)

docker_client = docker.from_env()


def start_agent():
    agent_container = docker_client.containers.get(AGENT_CONTAINER)
    if agent_container.status == "exited":
        agent_container.start()
    elif agent_container.status == "running":
        agent_container.restart()


def agent_container_running() -> bool:
    """Whether the agent is up right now, asked of Docker rather than inferred
    from what the supervisor last saw. The agent restarts itself after every
    task, a rollback, or a crash, and those restarts are invisible here."""
    try:
        return docker_client.containers.get(AGENT_CONTAINER).status == "running"
    except Exception:
        return False
