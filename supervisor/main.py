import json
import os
import pika
import subprocess
import time

import docker

from database.crud import get_snapshot_by_status

AGENT_REPO = "/agent"
AGENT_ERROR_LOG = "/logs/agent_error.log"
AGENT_CONTAINER = "hyperagent_agent"
RABBITMQ_URL = "amqp://supervisor:12345@rabbitmq:5672/"
ERRORS_QUEUE = "error_queue"
COMMANDS_EXCHANGE = "agent_exchange"
ROUTING_KEY_COMMANDS = "agent"

docker_client = docker.from_env()

def rollback_agent():
    snapshot = get_snapshot_by_status("STABLE")
    if not snapshot:
        raise ValueError("Database has not STABLE snapshot")
    _, snapshot_sha, _ = snapshot
    subprocess.run(["git", "checkout", "-f", snapshot_sha], cwd=AGENT_REPO, check=True)

def start_agent():
    agent_container = docker_client.containers.get(AGENT_CONTAINER)
    if agent_container.status == "exited":
        agent_container.start()
    elif agent_container.status == "running":
        agent_container.restart()


def send_start_command(error_text):
    message = {
        "command": "start",
    }
    if error_text:
        message["error_text"] = error_text
    body = json.dumps(message, ensure_ascii=False)
    command_connection = pika.BlockingConnection(pika.URLParameters(RABBITMQ_URL))
    command_channel = connection.channel()
    command_channel.basic_publish(
        exchange=COMMANDS_EXCHANGE,
        routing_key=ROUTING_KEY_COMMANDS,
        body=body,
        properties=pika.BasicProperties(
            delivery_mode=2,
            content_type="application/json"
        )
    )
    command_connection.close()

def supervise_agent(ch, method, properties, body):
    #if not os.path.exists(AGENT_ERROR_LOG) or os.path.getsize(AGENT_ERROR_LOG) == 0:
        #return
    error_text = body.decode('utf-8')
    try:
        rollback_agent()
        start_agent()
        send_start_command(error_text)
        ch.basic_ack(delivery_tag=method.delivery_tag)
    except Exception as e:
        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)


if __name__ == "__main__":
    connection = pika.BlockingConnection(pika.URLParameters(RABBITMQ_URL))
    channel = connection.channel()
    channel.basic_qos(prefetch_count=1)
    channel.basic_consume(queue=ERRORS_QUEUE, on_message_callback=supervise_agent)
    channel.start_consuming()
