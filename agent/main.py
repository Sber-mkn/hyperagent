from agent.llminterface.client.providers.ollama_client import OllamaClient
from agent.llminterface.client.llm_chat import LLMChat

from typing import Callable, Tuple, Any, Optional
import rich

OLLAMA_URL = "http://localhost:11434/api/chat"

if __name__ == "__main__":
    client = OllamaClient(url="http://localhost:11434/api/chat", model="gemma4:e2b")

    def chunk_out() -> Tuple[Callable[[str], None], Callable[[str], None]]:
        think: bool = False
        content: bool = False

        def print_think(s: str):
            nonlocal think, content

            if not think:
                if content:
                    print(end="\n\n")
                print("Размышление:")
                content = False
                think = True

            print(s, end="", flush=True)


        def print_content(s: str):
            nonlocal think, content

            if not content:
                if think:
                    print(end="\n\n")
                print("Ответ:")
                content = True
                think = False

            print(s, end="", flush=True)

        return print_think, print_content

    on_think, on_content = chunk_out()

    chat = client.stream(
        LLMChat([
            {"role": "system", "content": "Ты полезный ассистент."},
            {"role": "user", "content": "Привет, кто ты?"}
        ]),
        on_chunk_think=on_think,
        on_chunk_content=on_content
    )
    print()
    rich.print(chat)