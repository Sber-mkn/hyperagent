"""One-command test runner for the Hyperagent Docker stack.

Usage:
    python run_stack.py                 # start containers, then type prompts interactively
    python run_stack.py "your task"     # start containers, send one task, print progress

It starts all containers, waits for the supervisor's "ready" message,
sends your prompt to the agent, prints client queue progress messages,
and streams agent container logs until the next "ready" or "result".
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time

import pika

RABBITMQ_URL = "amqp://client:12345@localhost:5672/"
EXCHANGE = "agent_exchange"
CLIENT_QUEUE = "client_queue"
AGENT_ROUTING_KEY = "agent"


def compose_up() -> None:
    print(">>> Starting Docker stack (without client service) ...")
    subprocess.run(
        ["docker", "compose", "up", "--build", "-d", "db", "rabbitmq_agent", "supervisor", "agent"],
        check=True,
    )


def stream_agent_logs(stop: threading.Event) -> None:
    proc = subprocess.Popen(
        ["docker", "logs", "-f", "--since", "1s", "hyperagent_agent"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        if proc.stdout is None:
            return
        for line in proc.stdout:
            if stop.is_set():
                break
            if "pika" not in line:
                print(f"[agent] {line}", end="")
    finally:
        proc.terminate()


def connect(retries: int = 30) -> pika.BlockingConnection:
    for attempt in range(retries):
        try:
            return pika.BlockingConnection(pika.URLParameters(RABBITMQ_URL))
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(2)
    raise RuntimeError("unreachable")


def print_client_message(message: dict) -> None:
    message_type = message.get("type")
    if message_type == "agent_message":
        print(f"[agent_message:{message.get('message_type')}] {message.get('message')}")
    elif message_type == "result":
        print("\n================ RESULT ================")
        print(f"Status   : {message.get('status')}")
        print(f"Answer   : {message.get('answer')}")
        print(f"Artifacts: {message.get('artifacts')}")
        print("========================================\n")


def wait_for_message(channel, wanted_types: set[str], timeout: int = 600) -> dict | None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        method, _props, body = channel.basic_get(CLIENT_QUEUE, auto_ack=True)
        if body is not None:
            message = json.loads(body.decode("utf-8"))
            print_client_message(message)
            if message.get("type") in wanted_types:
                return message
        time.sleep(1)
    return None


def send_task(channel, task: str) -> None:
    channel.basic_publish(
        exchange=EXCHANGE,
        routing_key=AGENT_ROUTING_KEY,
        body=json.dumps({"task": task, "command": "start"}, ensure_ascii=False),
        properties=pika.BasicProperties(delivery_mode=2, content_type="application/json"),
    )
    print(">>> Task sent, waiting for READY/result (watch the [agent] log lines) ...")


def run_one_task(channel, task: str) -> None:
    stop = threading.Event()
    log_thread = threading.Thread(target=stream_agent_logs, args=(stop,), daemon=True)
    log_thread.start()
    send_task(channel, task)
    result = wait_for_message(channel, {"ready", "result"})
    stop.set()
    if result is None:
        print("!!! Timed out waiting for READY/result. Check `docker logs hyperagent_agent`.")
        return
    if result.get("type") == "ready":
        print(">>> Hyperagent is READY\n")


def main() -> None:
    compose_up()
    connection = connect()
    channel = connection.channel()
    print(">>> Waiting for Hyperagent READY ...")
    if wait_for_message(channel, {"ready"}, timeout=120) is None:
        print(">>> No ready message seen (maybe consumed earlier), continuing anyway.")
    print(">>> Hyperagent is READY\n")

    if len(sys.argv) > 1:
        run_one_task(channel, " ".join(sys.argv[1:]))
    else:
        while True:
            try:
                task = input("Enter your request (or 'quit'): ").strip()
            except EOFError, KeyboardInterrupt:
                break
            if not task or task.lower() in {"quit", "exit"}:
                break
            run_one_task(channel, task)

    connection.close()
    print(">>> Done. Stack is still running (stop it with: docker compose down)")


if __name__ == "__main__":
    main()
