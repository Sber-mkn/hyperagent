from python:3.14-slim
run apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*
workdir /hyperagent
copy requirements/supervisor.txt requirements.txt
run pip install --no-cache-dir --upgrade -r requirements.txt

COPY supervisor/ ./supervisor/
COPY database/ ./database/
COPY rabbitmq/ ./rabbitmq/
COPY requirements/ ./requirements/
COPY contracts/ ./contracts/

env PYTHONPATH=/hyperagent

cmd ["python", "supervisor/main.py"]
