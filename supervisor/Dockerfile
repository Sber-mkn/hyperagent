from python:3.13-slim
workdir /hyperagent/supervisor
copy requirements.txt .
run pip install --no-cache-dir --upgrade -r requirements.txt
copy .. .
env PYTHONPATH=/hyperagent
cmd ["python", "main.py"]