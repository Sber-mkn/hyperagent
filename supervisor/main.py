from rabbitmq_servise.rabbitmq_supervisor import RabbitMQServise

AGENT_ERROR_LOG = "/logs/agent_error.log"

if __name__ == "__main__":
    rabbitmq = RabbitMQServise()
    rabbitmq.start_consuming()


