from agent.llminterface.client.providers.ollama_client import OllamaClient
from agent.llminterface.client.llm_chat import LLMChat

from typing import Callable, Tuple, Any, Optional, List, Dict
import rich

from agent.llminterface.llm_chain.llm_chain import GraphNode, Unit

OLLAMA_URL = "http://100.93.59.55:11434/api/chat"

if __name__ == "__main__":
    client = OllamaClient(url=OLLAMA_URL, model="gemma4:e2b")

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


    def user_input() -> str:
        return input("Введите запрос: ")

    def create_message(content: str, role: str) -> List[Dict[str, Any]]:
        return [
            {"role": role, "content": content}
        ]

    def llm(messages: List[Dict[str, Any]], on_think, on_content) -> LLMChat:
        chat = client.stream(
            LLMChat(messages),
            on_chunk_think=on_think,
            on_chunk_content=on_content
        )

        return chat

    def stroutput(chat: LLMChat) -> str:
        return chat[-1].content

    start = GraphNode.start()

    start >> (user_input, "input") >> ("input", Unit(create_message, role="user"), "messages") >> ("messages", Unit(llm, on_think=on_think, on_content=on_content), "chat") >> ("chat", stroutput, "output")

    rich.print(start())

    # chat = client.stream(
    #     LLMChat([
    #         {"role": "system", "content": "Ты полезный ассистент."},
    #         {"role": "user", "content": "Привет, кто ты?"}
    #     ]),
    #     on_chunk_think=on_think,
    #     on_chunk_content=on_content
    # )
    # print()
    # rich.print(chat)