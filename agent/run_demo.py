"""Run the V3 agent (layered memory L0–L3, ReAct loop).

Usage (from repo root):
    py -m agent.run_demo
    py -m agent.run_demo "your task here"

Requires agent/.env with LLM_PROVIDER=openrouter and OPENROUTER_API_KEY.
"""

from __future__ import annotations

import sys
from pathlib import Path

if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.agent_loop import ReactAgent
from agent.clients import build_client, default_model
from agent.config import DATA_DIR, SUMMARIZER_MODEL
from agent.memory.store import MemoryStore

DEFAULT_TASK = (
    "Write a Python function that returns the nth Fibonacci number, "
    "save it to fib.py, and run it to print fib(10)."
)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    task = " ".join(sys.argv[1:]).strip() or DEFAULT_TASK
    MemoryStore.reset(DATA_DIR)

    client = build_client()
    model = default_model()

    print(f"Provider : {client.provider}")
    print(f"Model    : {model}")
    print(f"Task     : {task}\n")

    agent = ReactAgent(
        client=client,
        agent_model=model,
        summarizer_model=SUMMARIZER_MODEL,
    )

    try:
        result = agent.run(task)
    except Exception as exc:
        print(f"\nAgent run failed: {exc}")
        print("Check agent/.env — OPENROUTER_API_KEY and LLM_PROVIDER=openrouter")
        raise SystemExit(1) from exc

    print("\n" + "=" * 64)
    print("ANSWER")
    print("=" * 64)
    print(result.answer)

    print("\n" + "=" * 64)
    print("METRICS")
    print("=" * 64)
    print(f"  wall time        : {result.elapsed_s:.2f} s")
    print(f"  model steps      : {result.iterations}")
    print(f"  tool calls       : {result.tool_calls}")
    print(f"  L3 compressions  : {result.compressions}")
    print(f"  input tokens     : {result.input_tokens}")
    print(f"  output tokens    : {result.output_tokens}")
    print(f"  total tokens     : {result.input_tokens + result.output_tokens}")
    print(f"  memory files     : agent/data/")


if __name__ == "__main__":
    main()
