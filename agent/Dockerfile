from python:3.13-slim
workdir /hyperagent/agent
copy requirements.txt .
run pip install --no-cache-dir -r requirements.txt
env PYTHONPATH=/hyperagent
cmd ["python", "main.py"]