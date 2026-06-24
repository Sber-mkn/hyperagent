from python:3.13-slim
workdir /hyperagent
copy requirements.txt .
run pip install --no-cache-dir -r requirements.txt
copy . .
env PYTHONPATH=/hyperagent
cmd ["python", "main.py"]