from python:3.14-slim
workdir /hyperagent/client
copy requirements/client.txt requirements.txt
run pip install --no-cache-dir --upgrade -r requirements.txt
env PYTHONPATH=/hyperagent
