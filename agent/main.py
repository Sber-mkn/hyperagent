from agent.llminterface.client.providers.ollama_client import OllamaClient
from agent.llminterface.client.llm_chat import LLMChat
from agent.llminterface.agent_graph.agent_state import AgentState
from agent.react_agent import build_agent
from agent.ui import render_final

OLLAMA_URL = "http://0.0.0.0:11434/api/chat"
MODEL = "qwen3.6:35b"
NAMER = "gemma4:e2b"

if __name__ == "__main__":
    client = OllamaClient(url=OLLAMA_URL)
    agent = build_agent(client, MODEL, NAMER)

    question = input("Запрос: ")
    initial = AgentState({
        "chat": LLMChat([{"role": "user", "content": question}]),
        "revisions": 0,
        "title": None,
    })

    final = agent.run(initial)

    render_final(final)
