import json

"""
def receive_command(self, ch, method, properties, body):
    message = json.loads(body.decode("utf-8"))
    command = message.get("command", "")
    error_text = message.get("error_text", None)
    snapshot_text = message.get("snapshot_text", None)
    if command == "start":
        try:

        except Exception as e:
            error_text = traceback.format_exc()
            rabbitmq.send_error(error_text)
            sys.exit(1)

"""