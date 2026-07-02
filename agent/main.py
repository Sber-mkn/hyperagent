from agent.llminterface.client.providers.ollama_client import OllamaClient
from agent.llminterface.client.llm_chat import LLMChat
from agent.llminterface.agent_graph.agent_state import AgentState
from agent.react_agent import build_agent
from agent.tools import tools_spec

OLLAMA_URL = "http://100.93.59.55:11434/api/chat"
ORCHESTRATOR = "gemma4:e2b"
NAMER = "gemma4:e2b"
REFLECTOR = "gemma4:e2b"


def stream_print():
    is_think = False
    is_content = False

    def on_think(chunk: str):
        nonlocal is_think, is_content
        if is_content:
            print(end="\n\n")
            is_content = False
        if not is_think:
            print("Размышление")
            is_think = True
        print(chunk, end="", flush=True)

    def on_content(chunk: str):
        nonlocal is_think, is_content
        if is_think:
            print(end="\n\n")
            is_think = False
        if not is_content:
            print("Размышление")
            is_content = True
        print(chunk, end="", flush=True)

    return on_think, on_content


on_think, on_content = stream_print()

if __name__ == "__main__":
    client = OllamaClient(url=OLLAMA_URL)
    agent = build_agent(client)

    question = input("Запрос: ")
    initial = AgentState({
        "chat": LLMChat([{"role": "user", "content": question}]),
        "orchestrator_model": ORCHESTRATOR,
        "namer_model": NAMER,
        "reflector_model": REFLECTOR,
        "orchestrator_prompt": "Ты ассистент, который должен помогать пользователю с решением различных задач. Во "
                               "время работы ты можешь пользоваться любыми предоставленными тебе инструментами. Также "
                               "при необходимости ты можешь писать python-код и запускать его с помощью "
                               "соответственных инстурментов. Всегда проверяй факты с помощью поиска в интернете, а "
                               "также если возникают проблемы с использованием API, библиотек и т.д. - также обращайся "
                               "за помощью в интернет.",
        "namer_prompt": "Придумай очень короткое название для беседы (3 - 5 слова) по запросу пльзователя. Ответь "
                        "только названием.",
        "reflector_prompt": "Твоя задача оценить решение задачи представленное в этом диалоге. Если представленное ты "
                            "считаешь, что решение правильное и соответствует запросу пользователя, начни сообщение со "
                            "слова 'Окей', иначе - кратко опиши проблему.",
        "tools": tools_spec(),
        "on_think": on_think,
        "on_content": on_content,
        "revisions": 0,
        "title": None,
    })

    final = agent.stream(initial)
    print(f"title: {final['title']}")