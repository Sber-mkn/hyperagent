from python:3.13-slim
workdir /hyperagent
copy requirements/agent.txt requirements.txt
run pip install --no-cache-dir --upgrade -r requirements.txt
env PYTHONPATH=/hyperagent
cmd ["python", "agent_immutable/main.py"]