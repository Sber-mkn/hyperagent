from agent_immutable.rabbitmq_agent import RabbitMQAgent

_rabbitmq: RabbitMQAgent | None = None


def set_rabbitmq(service: RabbitMQAgent) -> None:
    global _rabbitmq
    _rabbitmq = service


def get_rabbitmq() -> RabbitMQAgent:
    if _rabbitmq is None:
        raise RuntimeError("RabbitMQAgent is not initialized")
    return _rabbitmq
