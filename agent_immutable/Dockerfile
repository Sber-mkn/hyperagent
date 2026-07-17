from python:3.14-slim
run apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*
workdir /hyperagent
copy requirements/agent.txt requirements.txt
run pip install --no-cache-dir --upgrade -r requirements.txt

COPY agent/ ./agent/
COPY agent_immutable/ ./agent_immutable/
COPY database/agent/ ./database/agent/
COPY rabbitmq/ ./rabbitmq/
COPY constitution/ ./constitution/

env PYTHONPATH=/hyperagent
cmd ["python", "agent_immutable/main.py"]
