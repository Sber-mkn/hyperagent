import json
import re
from typing import Callable, Optional, Any, Union

from agent.llminterface.llm_client import LLMClient
from agent.llminterface.agentgraph.node import NodeStream


def loads_loose(content: str) -> Any:
    """json.loads, устойчивый к обёртке в markdown-фенсы (```json ... ```).
    Модели иногда оборачивают структурированный ответ в ``` несмотря на response_format —
    из-за чего обычный json.loads падает. Сначала пробуем как есть, затем снимаем фенсы,
    затем вырезаем первый сбалансированный объект {...}."""
    if not isinstance(content, str):
        raise TypeError("content должен быть str")
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass
    s = content.strip()
    m = re.match(r"^```[a-zA-Z0-9]*\s*\n(.*?)\n?```$", s, re.DOTALL)
    if m:
        s = m.group(1).strip()
        return json.loads(s)
    start = s.find("{")
    end = s.rfind("}")
    if start != -1 and end > start:
        return json.loads(s[start:end + 1])
    raise json.JSONDecodeError("не удалось извлечь JSON", content, 0)


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


class LLMNode:
    """Узел на базе LLMClient"""
    def __init__(
            self,
            client: LLMClient,
            system: Optional[str] = None,
            tools: Optional[list] = None,   # list[dict] или list функций с @agent_tool
            messages_key: str = "messages",
            output_key: Optional[str] = "output",
            response_format: Optional[dict] = None,
            json_state_map: Optional[dict[str, str]] = None,
            extra_state: Optional[dict] = None,
            **chat_kwargs: Any
    ):
        self.client = client
        self.system = system
        self.tools = _normalize_tool_schemas(tools)
        self.messages_key = messages_key
        self.output_key = output_key
        self.response_format = response_format
        self.json_state_map = json_state_map or {}
        self.extra_state = extra_state or {}
        self.chat_kwargs = chat_kwargs
        if response_format:
            self.chat_kwargs["format"] = response_format

    def _prepare_messages(self, state: dict) -> list[dict]:
        messages = list(state.get(self.messages_key, []))
        if self.system:
            messages = [{"role": "system", "content": self.system}] + messages
        return messages

    def _build_update(self, content: str, tool_calls: Optional[list],
                      thinking: Optional[str] = None, usage: Optional[Any] = None) -> dict:
        ai_msg: dict = {"role": "assistant", "content": content}
        if thinking:
            ai_msg["thinking"] = thinking
        if tool_calls:
            ai_msg["tool_calls"] = tool_calls
        update: dict = {self.messages_key: [ai_msg], "step": 1, "llm_calls": 1}
        if usage is not None:
            update["prompt_tokens"] = getattr(usage, "prompt_tokens", 0) or 0
            update["completion_tokens"] = getattr(usage, "completion_tokens", 0) or 0
            update["total_tokens"] = getattr(usage, "total_tokens", 0) or 0
        # output обновляем только содержательным ответом: пустой content
        # (например, ход модели, состоящий лишь из thinking) не должен затирать итог
        if self.output_key and content and content.strip():
            update[self.output_key] = content
        if thinking:
            update["thinking"] = thinking

        if self.json_state_map:
            try:
                parsed = loads_loose(content)
                if isinstance(parsed, dict):
                    for json_key, state_key in self.json_state_map.items():
                        if json_key in parsed:
                            update[state_key] = parsed[json_key]
            except (json.JSONDecodeError, TypeError):
                pass

        update.update(self.extra_state)
        return update

    def __call__(self, state: dict) -> dict:
        messages = self._prepare_messages(state)
        resp = self.client.chat(messages, tools=self.tools, **self.chat_kwargs)
        return self._build_update(resp.content, resp.tool_calls, resp.thinking, resp.usage)

    def stream(self, state: dict) -> NodeStream:
        """Возвращает NodeStream. Итерируется по токенам, в update доступен готовый dict-update"""
        messages = self._prepare_messages(state)
        resp_stream = self.client.stream(messages, tools=self.tools, **self.chat_kwargs)

        def gen():
            for chunk in resp_stream:          # chunk: StreamChunk(type, text)
                yield chunk
            final = resp_stream.response
            holder.update = self._build_update(final.content, final.tool_calls, final.thinking, final.usage)
        holder = NodeStream(gen())
        return holder


class ToolEvent:
    __slots__ = ("name", "args", "result", "error")

    def __init__(self, name: str, args: dict,
                 result: Optional[str] = None, error: Optional[Exception] = None):
        self.name = name
        self.args = args
        self.result = result
        self.error = error

    @property
    def is_call(self) -> bool:
        return self.result is None and self.error is None

    def __repr__(self) -> str:
        if self.is_call:
            return f"ToolEvent(call  {self.name!r}, args={self.args})"
        if self.error:
            return f"ToolEvent(error {self.name!r}, error={self.error})"
        return f"ToolEvent(result {self.name!r}, result={self.result!r})"


class ToolNode:
    """Выполняет tool_calls из последнего сообщения ассистента"""

    def __init__(self, tools: Union[dict[str, Callable], list[Callable]],
                 messages_key: str = "messages",
                 on_tool_event: Optional[Callable[[ToolEvent], None]] = None):
        self.tools = _normalize_tool_map(tools)
        self.messages_key = messages_key
        self._on_event = on_tool_event

    def _emit(self, event: ToolEvent) -> None:
        if self._on_event:
            self._on_event(event)

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

            self._emit(ToolEvent(name, args))

            if name not in self.tools:
                error_msg = f"Ошибка: инструмент '{name}' не зарегистрирован"
                self._emit(ToolEvent(name, args, result=error_msg))
                content = error_msg
            else:
                try:
                    content = str(self.tools[name](**args))
                    self._emit(ToolEvent(name, args, result=content))
                except Exception as e:
                    self._emit(ToolEvent(name, args, error=e))
                    content = f"Ошибка инструмента '{name}': {e}"
            results.append({"role": "tool", "tool_name": name, "content": content})

        return {self.messages_key: results}


def tools_condition(state: dict, messages_key: str = "messages") -> str:
    """Если последнее сообщение содержит tool_calls, то идёт в tools, иначе - завершение"""
    messages = state.get(messages_key, [])
    if messages and messages[-1].get("tool_calls"):
        return "tools"
    return "end"


def reflector_condition(state: dict, max_reflections: int = 2) -> str:
    if state.get("reflections", 0) >= max_reflections:
        return "end"
    return "end" if state.get("approved") else "agent"
