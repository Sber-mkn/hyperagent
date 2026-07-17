# Hyperagent — V3 agent + supervisor integration

Self-improving coding agent (V3 ReAct loop, layered memory L0–L3) integrated with Docker, RabbitMQ, Postgres snapshots, and supervisor rollback.

**Branch in this repo:** `integration/v3_supervisor` (V3 `agent/` + `local_supervisor` stack).

## Quick start (local, no Docker)

```bash
cp agent/.env.example agent/.env
# Edit agent/.env — set OPENROUTER_API_KEY

pip install -r agent/requirements.txt
python -m agent.run_demo "Create workdir/hello.py that prints hello and run it"
```

## Quick start (Docker — full stack)

```bash
docker-compose --profile router up --build
```

Then start the client from the sibling repository:

```bash
cd ../hyperagent-client
pip install -r requirements.txt
python -m client.qt_main
```

Log in in the client UI. The client sends login/password to the router first;
after that the router starts or reuses the user's agent containers and returns
personal RabbitMQ connection data.

Send a task in the client, e.g.:

```
Create /hyperagent/workdir/hello.py that prints hello, then run it with run_python
```

Wait for `--- Result ---` (15–30s). Files appear in `./workdir/` on the host.

## Layout

| Path | Role |
|------|------|
| `agent/` | V3 mutable agent (ReAct loop, memory, tools, LLM clients) |
| `agent_immutable/` | Immutable entry — RabbitMQ, try/except, calls `agent_logic()` |
| `supervisor/` | Git snapshots, rollback, container restart |
| `../hyperagent-client/` | Standalone client repository |
| `constitution/` | Read-only L0 rules (mounted ro in Docker) |
| `database/` | Postgres schema + CRUD for snapshots |
| `rabbitmq/` | Exchange, queues, shared service |
| `workdir/` | User task artifacts (hello.py, etc.) |
| `docs/` | Integration guides + handoff for Devin |

## Environment variables (`agent/.env`)

| Variable | Default | Purpose |
|----------|---------|---------|
| `LLM_PROVIDER` | `openrouter` | `openrouter` or `ollama` |
| `OPENROUTER_API_KEY` | — | **Required** for OpenRouter |
| `AGENT_MODEL` | `qwen/qwen3-coder` | Main model (must support structured tool_calls) |
| `SUMMARIZER_MODEL` | `qwen/qwen3-8b` | L2→L3 compression (cheaper) |
| `V3_MAX_OUTPUT_TOKENS` | `512` | Cap per model call |
| `V3_MAX_ITERATIONS` | `20` | ReAct loop limit |

Docker also sets: `V3_DATA_DIR`, `AGENT_WORKDIR`, `AGENT_ROOT` (see `docker-compose.yml`).

## Services (docker compose)

| Service | Port | Notes |
|---------|------|-------|
| `rabbitmq` | 5672, 15672 (UI) | guest/guest |
| `db` | 5432 | admin/12345, `hyperagent_db` |
| `agent` | — | Restarts per task |
| `supervisor` | — | Handles commit/ack/error |

## Verification checklist (Devin / CI)

1. **Local:** `python -m agent.run_demo` → `tool_calls >= 2`, answer printed
2. **Docker:** external client task → `status: success`, file in `workdir/`
3. **Import:** `from agent.main import agent_logic` inside agent container
4. **Logs:** agent shows `--- step N ---` and `tool write_file:`

## Docs

- [`docs/HANDOFF_TO_DEVON.md`](docs/HANDOFF_TO_DEVON.md) — full history, V1–V5, bugs fixed
- [`docs/INTEGRATION_STEPS.md`](docs/INTEGRATION_STEPS.md) — step-by-step integration
- [`docs/INTEGRATION_SUPERVISOR.md`](docs/INTEGRATION_SUPERVISOR.md) — supervisor wiring
- [`docs/INTEGRATION_LOGIC_AND_WHY.md`](docs/INTEGRATION_LOGIC_AND_WHY.md) — architecture reasoning

## Phase status

| Phase | Status |
|-------|--------|
| A — Docker + V3 agent + client result | Done |
| B — Constitution L0, path guards | Partial |
| C — Self-mod bridge (`commit_self_changes`) | Not done |

## Requirements

- Python 3.14 (Docker images)
- OpenRouter API key (or Ollama for local-only)
- Docker + Docker Compose for full stack
