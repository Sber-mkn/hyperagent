import os
import docker

AGENT_REPO = "/agent"
AGENT_CONTAINER = os.getenv("AGENT_CONTAINER_NAME", f"hyperagent_agent_{os.getenv('LOGIN', 'unknown')}")

docker_client = docker.from_env()


def start_agent():
    agent_container = docker_client.containers.get(AGENT_CONTAINER)
    if agent_container.status == "exited":
        agent_container.start()
    elif agent_container.status == "running":
        agent_container.restart()
