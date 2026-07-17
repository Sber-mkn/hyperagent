"""Terminal callbacks for running agent.main directly."""

from __future__ import annotations

import json
from typing import Any

from agent.llminterface.client.llm_chat import LLMMessage
from agent.tools.registry import execute_tool_from_json


def on_think_and_content():
    showing_thought, showing_content = False, False

    def on_think(chunk: str) -> None:
        nonlocal showing_thought, showing_content
        if not showing_thought:
            print("\nThinking: ", end="", flush=True)
            showing_thought, showing_content = True, False
        print(chunk, end="", flush=True)

    def on_content(chunk: str) -> None:
        nonlocal showing_thought, showing_content
        if not showing_content:
            if showing_thought:
                print(flush=True)
            print("\nContent: ", end="", flush=True)
            showing_content, showing_thought = True, False
        print(chunk, end="", flush=True)

    return on_think, on_content


def on_title(title: str) -> None:
    print(f"\n--- {title} ---")


def on_tool(payload: dict[str, Any]) -> Any:
    name, result = execute_tool_from_json(json.dumps(payload, ensure_ascii=False))
    print(f"\nClient tool {name}: {result}")
    return result


def on_tool_call(name: str, arguments: Any, target: str, result_preview: str) -> None:
    print(f"\nTool {name} [{target}] {arguments} -> {result_preview}")


def on_end_message(message: LLMMessage) -> None:
    print("\nMessage finished")
    if message.tokens:
        print(f"Tokens: prompt={message.tokens.prompt}, response={message.tokens.response}")
    if message.duration:
        print(
            f"Time: load={message.duration.load}, "
            f"prompt={message.duration.prompt}, "
            f"response={message.duration.response}"
        )


def on_start_message(model: str) -> None:
    print(f"\nModel started: {model}")
