from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from agent.config import DATA_DIR, L2_TOKEN_BUDGET, MAX_ITERATIONS, MAX_OUTPUT_TOKENS, TEXT_ONLY_STEP_LIMIT
from agent.llminterface.client.llm_client import LLMClient
from agent.memory.context_manager import ContextManager
from agent.memory.store import MemoryStore, Turn
from agent.memory.summarizer import Summarizer
from agent.tools import run_tool_calls, tools_spec


@dataclass
class AgentResult:
    answer: str
    iterations: int
    tool_calls: int
    input_tokens: int
    output_tokens: int
    elapsed_s: float
    compressions: int = 0


@dataclass
class ReactAgent:
    """Single-model ReAct loop with layered memory (V3)."""

    client: LLMClient
    agent_model: str
    summarizer_model: str
    data_dir: str | None = None
    l2_token_budget: int = L2_TOKEN_BUDGET
    max_iterations: int = MAX_ITERATIONS
    verbose: bool = True

    _store: MemoryStore | None = field(default=None, init=False, repr=False)
    _context: ContextManager | None = field(default=None, init=False, repr=False)
    _summarizer: Summarizer | None = field(default=None, init=False, repr=False)
    _metrics: dict[str, int] = field(default_factory=lambda: {"in": 0, "out": 0, "tools": 0}, init=False)

    def _log(self, text: str) -> None:
        if self.verbose:
            print(text, flush=True)

    def _ensure_session(self) -> None:
        if self._store is None:
            root = DATA_DIR if self.data_dir is None else self.data_dir
            self._store = MemoryStore.open(root, l2_token_budget=self.l2_token_budget)
            self._context = ContextManager(self._store)
            self._summarizer = Summarizer(self.client, self.summarizer_model)

    def _compress_if_needed(self) -> bool:
        assert self._store and self._summarizer
        return self._store.maybe_compress(self._summarizer.summarize)

    def _record_usage(self, message) -> None:
        tokens = getattr(message, "tokens", None)
        if tokens:
            self._metrics["in"] += int(tokens.prompt or 0)
            self._metrics["out"] += int(tokens.response or 0)

    def run(self, task: str) -> AgentResult:
        self._ensure_session()
        assert self._store and self._context

        self._store.set_task(task)
        self._metrics = {"in": 0, "out": 0, "tools": 0}
        compressions = 0
        start = time.perf_counter()

        final_answer = ""
        text_only_steps = 0
        for step in range(1, self.max_iterations + 1):
            if self._compress_if_needed():
                compressions += 1

            chat = self._context.build_working_chat()
            self._log(f"\n--- step {step} ---")
            self._log(f"calling {self.agent_model} ...")
            t0 = time.perf_counter()
            send_kwargs: dict[str, Any] = {
                "model": self.agent_model,
                "tools": tools_spec(),
                "tool_choice": "auto",
                "temperature": 0,
                "max_tokens": MAX_OUTPUT_TOKENS,
            }
            reply_chat = self.client.send(chat, **send_kwargs)
            self._log(f"model replied in {time.perf_counter() - t0:.1f}s")
            assistant = reply_chat[-1]
            self._record_usage(assistant)

            content = assistant.content or ""
            tool_calls = assistant.tool_calls or []
            self._store.append_turn(
                Turn(role="assistant", content=content, tool_calls=tool_calls or None)
            )

            if tool_calls:
                text_only_steps = 0
                results = run_tool_calls(tool_calls)
                for name, result, call_id in results:
                    self._metrics["tools"] += 1
                    self._store.append_turn(
                        Turn(
                            role="tool",
                            content=result,
                            tool_name=name,
                            tool_call_id=call_id,
                        )
                    )
                    preview = result if len(result) < 400 else result[:400] + "..."
                    self._log(f"tool {name}: {preview}")
                continue

            if self._metrics["tools"] == 0:
                text_only_steps += 1
                self._log("model replied with text but no tools yet — continuing")
                if text_only_steps >= TEXT_ONLY_STEP_LIMIT:
                    self._log(
                        f"stopping after {text_only_steps} text-only replies without tools"
                    )
                    final_answer = content.strip() or "(model did not use tools)"
                    break
                continue

            final_answer = content.strip()
            if final_answer:
                break

        elapsed = time.perf_counter() - start
        return AgentResult(
            answer=final_answer or "(no answer produced)",
            iterations=step,
            tool_calls=self._metrics["tools"],
            input_tokens=self._metrics["in"],
            output_tokens=self._metrics["out"],
            elapsed_s=elapsed,
            compressions=compressions,
        )
