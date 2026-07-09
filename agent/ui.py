from math import floor, ceil

from agent.llminterface.client.llm_chat import LLMMessage
from agent.tools.registry import execute_tool_from_json

import rich
import json


def on_think_and_content():
    think, content = False, False

    def on_think(chunk: str):
        nonlocal think, content
        if not think:
            print("\nThinking: ", end="", flush=True)
            think = True
            content = False
        print(chunk, end="", flush=True)

    def on_content(chunk: str):
        nonlocal think, content
        if not content:
            if think:
                print(flush=True)
            print("\nContent: ", end="", flush=True)
            content = True
            think = False
        print(chunk, end="", flush=True)

    return on_think, on_content

len_line = 80

def on_title(title: str):
    n = (len_line - len(title) - 2) / 2
    print(f"{floor(n) * "-"} {title} {ceil(n) * "-"}")


def on_tool(tool: str):
    rich.print(f"Вызван инструмент:\n{tool}")
    result = execute_tool_from_json(tool)
    print(f"Результат:\n{result}")
    return result

def on_end_message(message: LLMMessage):
    print(f"Сообщение закончилось, сводка:"
          f"\n\tТокены:"
          f"\n\t\tПромпт: {message.tokens.prompt}"
          f"\n\t\tГенерация: {message.tokens.response}"
          f"\n\tВремя:"
          f"\n\t\tЗагрузка: {message.duration.load}"
          f"\n\t\tРефил: {message.duration.prompt}"
          f"\n\t\tГенерация: {message.duration.response}")

def on_start_message(model: str):
    print(f"\nНачалось сообщение от модели {model}")
