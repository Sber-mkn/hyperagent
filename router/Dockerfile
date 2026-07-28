# The router shells out to `docker compose` to bring each user's stack up, so it
# needs the CLI and the compose plugin -- taken straight from their official
# image. Installing them from Docker's apt repository instead meant fetching a
# GPG key and a second package index at build time, which is the step that fails
# first behind a proxy, on a restricted network, or whenever that repository has
# no packages yet for the base image's Debian release.
from docker:29-cli as docker_cli

from python:3.14-slim

copy --from=docker_cli /usr/local/bin/docker /usr/local/bin/docker
copy --from=docker_cli /usr/local/libexec/docker/cli-plugins/docker-compose \
     /usr/local/libexec/docker/cli-plugins/docker-compose

workdir /hyperagent
copy router/requirements.txt requirements.txt
run pip install --no-cache-dir --upgrade -r requirements.txt
copy . .
env PYTHONPATH=/hyperagent
cmd ["python", "router/main.py"]
