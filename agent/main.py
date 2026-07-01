from agent.llminterface.client.providers.ollama_client import OllamaClient
from agent.llminterface.client.llm_chat import LLMChat
from agent.llminterface.agent_chain.execs import *

from typing import Callable, Tuple, Any, Optional, List, Dict
import rich

from agent.llminterface.agent_chain.executable import *

OLLAMA_URL = "http://0.0.0.0:11434/api/chat"

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




    test = (
        ExecLambda(lambda : {"name": "Mikhail", "surname": "Putyata"})
        | ExecEffect(
            ExecEffect(ExecLambda(lambda d : f"{d['name']} {d['surname']}") | ExecPartial(print, end="\n\n"))
            | {
                "original": ExecPassthrough(),
                "name": lambda d : d["name"],
                "surname": lambda d: d["surname"],
                "full" : lambda d: d["surname"] + d["name"]
            }
            | ExecEffect(rich.print) | ExecCall(ExecPartial(print, end="\n\n"))
        )
    )


    rich.print(test.stream())