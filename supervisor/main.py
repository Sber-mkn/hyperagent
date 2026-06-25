import logging
import os
import subprocess
import time

import docker

from database.crud import get_snapshot_by_status

AGENT_REPO = "/agent"
AGENT_ERROR_LOG = "/logs/agent_error.log"
AGENT_CONTAINER = "hyperagent_agent"


def rollback_agent():
    snapshot_id, snapshot_sha, snapshot_modification = get_snapshot_by_status("STABLE")
    subprocess.run(["git", "checkout", "-f", snapshot_sha], cwd=AGENT_REPO, check=True)



def supervise_agent(container):
    if not os.path.exists(AGENT_ERROR_LOG) or os.path.getsize(AGENT_ERROR_LOG) == 0:
        return
    open(AGENT_ERROR_LOG, "w").close()
    rollback_agent()
    with open(AGENT_ERROR_LOG, encoding="utf-8") as f:
        error_text = f.read()
    container.start()


if __name__ == "__main__":
    client = docker.from_env()
    agent_container = client.containers.get(AGENT_CONTAINER)
    while True:
        try:
            supervise_agent(agent_container)
        except Exception as e:
            logging.error(e)
        time.sleep(5)
