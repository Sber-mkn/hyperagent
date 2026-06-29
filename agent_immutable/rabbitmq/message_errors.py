class MessagingError(Exception):
    pass


class MessagePublishError(MessagingError):
    def __init__(self, message: str, exchange: str, routing_key: str, body: str):
        self.exchange = exchange
        self.routing_key = routing_key
        self.body = body
        super().__init__(message)


class ConnectionLostError(MessagingError):
    pass


class ChannelError(MessagingError):
    pass
