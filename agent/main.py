from agent.llminterface.client.providers.ollama_client import OllamaClient
from agent.llminterface.client.llm_chat import LLMChat
from agent.llminterface.agent_graph.agent_state import AgentState
from agent.react_agent import build_agent
from agent.tools import tools_spec
from agent.ui import stream_print, render_final


from typing import Callable, Any, Dict, List, Optional
import json

OLLAMA_URL = "http://100.93.59.55:11434/api/chat"
ORCHESTRATOR = "ornith:9b"
NAMER = "gemma4:e2b"
REFLECTOR = "ornith:9b"


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
        "orchestrator_prompt": "Ты ассистент, который должен помогать пользователю с решением любых задач. Во "
                               "время работы ты можешь пользоваться любыми предоставленными тебе инструментами для того"
                               ", чтобы решить поставленную задачу. Также "
                               "при необходимости ты можешь писать python-код и запускать его с помощью "
                               "соответственных инстурментов. Всегда проверяй факты с помощью поиска в интернете, а "
                               "также если возникают проблемы с использованием API, библиотек и т.д. - также обращайся "
                               "за помощью в интернет."
                               ""
                               "Если пользователь просит что-то найти, то ты обязан не просто дать ему ссылки на нужные"
                               " ресурсы, а полностью ответить на вопрос. Твоих инструментов 100% хватает для решения "
                               "любой задачи.",
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
    render_final(final)


def agent_logic(
        user_message: str,
        error_text: str = "",
        on_think: Optional[Callable[[str], Any]] = None,
        on_content: Optional[Callable[[str], Any]] = None,
        on_tools: Optional[Callable[[Dict[str, Any]], Any]] = None,
        on_message: Optional[Callable[[Dict[str, Any]], Any]] = None
):
    client = OllamaClient(url=OLLAMA_URL)
    agent = build_agent(client)
    initial = AgentState({
        "chat": LLMChat([{"role": "user", "content": user_message}]),
        "orchestrator_model": ORCHESTRATOR,
        "namer_model": NAMER,
        "reflector_model": REFLECTOR,
        "orchestrator_prompt": "Ты ассистент, который должен помогать пользователю с решением любых задач. Во "
                               "время работы ты можешь пользоваться любыми предоставленными тебе инструментами для того"
                               ", чтобы решить поставленную задачу. Также "
                               "при необходимости ты можешь писать python-код и запускать его с помощью "
                               "соответствующих инстурментов. Всегда проверяй факты с помощью поиска в интернете, а "
                               "также если возникают проблемы с использованием API, библиотек и т.д. - также обращайся "
                               "за помощью в интернет."
                               ""
                               "Если пользователь просит что-то найти, то ты обязан не просто дать ему ссылки на нужные"
                               " ресурсы, а полностью ответить на вопрос. Твоих инструментов 100% хватает для решения "
                               "любой задачи.",
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






