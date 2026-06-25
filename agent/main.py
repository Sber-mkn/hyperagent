import json
from time import sleep

import pika
import traceback
import sys

AGENT_ERROR_LOG = "/logs/agent_error.log"
RABBITMQ_URL = "amqp://agent:12345@rabbitmq:5672/"
EXCHANGE = "agent_exchange"
COMMANDS_QUEUE = "agent_queue"
ROUTING_KEY_ERRORS = "error"
ROUTING_KEY_COMMON = "agent"

def send_error(error_text):
    try:
        connection = pika.BlockingConnection(pika.URLParameters(RABBITMQ_URL))
        channel = connection.channel()
        channel.basic_publish(
            exchange=EXCHANGE,
            routing_key=COMMANDS_QUEUE,
            body=error_text,
            properties=pika.BasicProperties(delivery_mode=2)
        )
        connection.close()
    except:
       pass

def send_commit(sha, commit):
    pass

def test_logic():
    sleep(3)
    raise ValueError("ERROR!!!")

def receive_command(ch, method, properties, body):
    message = json.loads(body.decode("utf-8"))
    command = message.get("command", "")
    error_text = message.get("error_text", None)
    print(error_text)
    if command == "start":
        test_logic()

def main():
    connection = pika.BlockingConnection(pika.URLParameters(RABBITMQ_URL))
    channel = connection.channel()
    channel.basic_qos(prefetch_count=1)
    channel.basic_consume(queue=COMMANDS_QUEUE, on_message_callback=receive_command)
    channel.start_consuming()

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        error_text = traceback.format_exc()
        send_error(error_text)
        sys.exit(1)
