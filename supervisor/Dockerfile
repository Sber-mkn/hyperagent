from python:3.14-slim
run apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*
workdir /hyperagent/supervisor
copy requirements/supervisor.txt requirements.txt
run pip install --no-cache-dir --upgrade -r requirements.txt
copy .. .
env PYTHONPATH=/hyperagent
cmd ["python", "main.py"]
