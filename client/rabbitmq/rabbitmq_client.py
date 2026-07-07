import json

import logging

import threading



import pika



from rabbitmq.rabbitmq_service import RabbitMQBase



USER = "client"

PASSWORD = "12345"

EXCHANGE = "agent_exchange"

CLIENT_QUEUE = "client_queue"

ROUTING_KEY = "agent"



logger = logging.getLogger(__name__)





class RabbitMQClient(RabbitMQBase):

    def __init__(

        self,

        user=USER,

        password=PASSWORD,

        exchange=EXCHANGE,

        queue=CLIENT_QUEUE,

        routing_key=ROUTING_KEY,

    ):

        super().__init__(user, password, exchange, queue, routing_key)

        self.pending_message = None

        self.ready_event = threading.Event()



    def receive_message(self, ch, method, properties, body):

        try:

            message = json.loads(body.decode("utf-8"))

            message_type = message.get("type", "")

            logger.info("Received message: %s", message_type)



            if message_type == "ready":

                self.ready_event.set()

                print("\nHyperagent is ready. Enter request: ")

                ch.basic_ack(delivery_tag=method.delivery_tag)



            elif message_type == "result":

                client = message.get("client", message)

                print("\n--- Result ---")

                print(f"Status   : {client.get('status') or message.get('status')}")

                print(f"Summary  : {client.get('summary') or message.get('summary')}")

                print(f"Answer   : {client.get('answer') or message.get('answer')}")

                print(f"Artifacts: {client.get('artifacts') or message.get('artifacts')}")

                metrics = message.get("metrics")

                if metrics:

                    print(f"Metrics  : {metrics}")

                print("--------------\n")

                self.ready_event.set()

                ch.basic_ack(delivery_tag=method.delivery_tag)



            else:

                logger.warning("Unknown message type: %s", message_type)

                ch.basic_ack(delivery_tag=method.delivery_tag)



        except Exception as e:

            logger.exception("Error processing message: %s", e)

            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)



    def publish(self):
        if self.pending_message is not None:
            body = json.dumps(self.pending_message, ensure_ascii=False)
            self.channel.basic_publish(
                exchange=self.exchange,
                routing_key=self.routing_key,
                body=body,
                properties=pika.BasicProperties(
                    delivery_mode=2,
                    content_type="application/json",
                ),
            )
            print("Waiting for result...")

            self.pending_message = None



    def input_loop(self):
        while True:
            self.ready_event.wait()
            self.ready_event.clear()

            try:
                user_input = input("").strip()
                user_input = user_input.encode("utf-8", errors="replace").decode("utf-8")

            except EOFError:
                print("\nStdin closed, exiting")
                break


            if not user_input:
                self.ready_event.set()
                continue

            self.pending_message = {
                "task": user_input,
                "command": "start",
            }

            self.connection.add_callback_threadsafe(self.publish)


