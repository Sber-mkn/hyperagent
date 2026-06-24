import json
from typing import Callable, Optional, Any, Union


def _normalize_tool_schemas(tools: Optional[list]) -> Optional[list[dict]]:
    """Приводит список инструментов к списку JSON-схем.
    Принимает уже готовые dict-схемы и/или функции с атрибутом tool_schema (@agent_tool)."""
    if not tools:
        return None
    schemas: list[dict] = []
    for t in tools:
        if isinstance(t, dict):
            schemas.append(t)
        elif callable(t) and hasattr(t, "tool_schema"):
            schemas.append(t.tool_schema)
        else:
            raise TypeError(f"Инструмент {t!r} должен быть dict-схемой или функцией с @agent_tool")
    return schemas


def _normalize_tool_map(tools: Union[dict, list]) -> dict[str, Callable]:
    """Приводит инструменты к словарю имя->функция.
    Принимает готовый dict или список функций (имя берётся из tool_name либо __name__)."""
    if isinstance(tools, dict):
        return tools
    result: dict[str, Callable] = {}
    for t in tools:
        name = getattr(t, "tool_name", None) or t.__name__
        result[name] = t
    return result


from agent.llminterface.llm_client import LLMClient
from agent.llminterface.agentgraph.node import NodeStream

class LLMNode:
    """Узел на базе LLMClient"""
    def __init__(
            self,
            client: LLMClient,
            system: Optional[str] = None,
            tools: Optional[list] = None,   # list[dict] или list функций с @agent_tool
            messages_key: str = "messages",
            output_key: str = "output",
            **chat_kwargs: Any
    ):
        self.client = client
        self.system = system
        self.tools = _normalize_tool_schemas(tools)
        self.messages_key = messages_key
        self.output_key = output_key
        self.chat_kwargs = chat_kwargs

    def _prepare_messages(self, state: dict) -> list[dict]:
        messages = list(state.get(self.messages_key, []))
        if self.system:
            messages = [{"role": "system", "content": self.system}] + messages
        return messages

    def _build_update(self, content: str, tool_calls: Optional[list],
                      thinking: Optional[str] = None) -> dict:
        ai_msg: dict = {"role": "assistant", "content": content}
        if thinking:
            ai_msg["thinking"] = thinking
        if tool_calls:
            ai_msg["tool_calls"] = tool_calls
        update: dict = {
            self.messages_key: [ai_msg],
            self.output_key: content,
            "step": 1
        }
        if thinking:
            update["thinking"] = thinking
        return update

    def __call__(self, state: dict) -> dict:
        messages = self._prepare_messages(state)
        resp = self.client.chat(messages, tools=self.tools, **self.chat_kwargs)
        return self._build_update(resp.content, resp.tool_calls, resp.thinking)

    def stream(self, state: dict) -> NodeStream:
        """Возвращает NodeStream. Итерируется по токенам, в update доступен готовый dict-update"""
        messages = self._prepare_messages(state)
        resp_stream = self.client.stream(messages, tools=self.tools, **self.chat_kwargs)

        def gen():
            for chunk in resp_stream:          # chunk: StreamChunk(type, text)
                yield chunk
            final = resp_stream.response
            holder.update = self._build_update(final.content, final.tool_calls, final.thinking)
        holder = NodeStream(gen())
        return holder


class ToolNode:
    """Выполняет tool_calls из последнего сообщения ассистента"""

    def __init__(self, tools: Union[dict[str, Callable], list[Callable]], messages_key: str = "messages"):
        self.tools = _normalize_tool_map(tools)
        self.messages_key = messages_key

    @staticmethod
    def _parse_args(args: Any) -> dict:
        if isinstance(args, str):
            return json.loads(args) if args.strip() else {}
        return args or {}

    def __call__(self, state: dict) -> dict:
        messages = state.get(self.messages_key, [])
        if not messages:
            return {}
        last = messages[-1]
        tool_calls = last.get("tool_calls") or []

        results: list[dict] = []

        for call in tool_calls:
            func_spec = call["function"]
            name = func_spec["name"]
            args = self._parse_args(func_spec.get("arguments"))

            if name not in self.tools:
                content = f"Ошибка: инструмент '{name}' не зарегистрирован"
            else:
                try:
                    content = str(self.tools[name](**args))
                except Exception as e:
                    content = f"Ошибка инструмента '{name}: {e}'"
            results.append({"role": "tool", "tool_name": name, "content": content})

        return {self.messages_key: results}


def tools_condition(state: dict, messages_key: str = "messages") -> str:
    """Если последнее сообщение содержит tool_calls, то идёт в tools, иначе - завершение"""
    messages = state.get(messages_key, [])
    if messages and messages[-1].get("tool_calls"):
        return "tools"
    return "end"


