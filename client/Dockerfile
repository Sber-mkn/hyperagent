FROM python:3.14-slim

WORKDIR /hyperagent/client
COPY requirements/client.txt requirements.txt
RUN pip install --no-cache-dir --upgrade -r requirements.txt

ENV PYTHONPATH=/hyperagent
