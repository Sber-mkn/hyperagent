from agent.llminterface.llm_client import LLMClient

from typing import Callable, Iterator, Optional


class NodeStream:
    """Держатель потока узла: __iter__ отдаёт токены, после прохода в .update лежит финальный dict-update"""

    def __init__(self, generator: Iterator[str]):
        self._generator = generator
        self.update: Optional[dict] = None

    def __iter__(self) -> Iterator[str]:
        return self._generator


class AgentNode:
    """Обёртка над исполнителем узла"""

    def __init__(self, name: str, executor: Callable | LLMClient):
        if isinstance(executor, LLMClient):
            # ленивый импорт, чтобы разорвать цикл node <-> nodes
            from agent.llminterface.agentgraph.nodes import LLMNode
            executor = LLMNode(executor)

        self.name: str = name
        self._executor = executor
        self._func: Callable[[dict], dict] = self._to_node_func(executor)

        self._stream_func: Optional[Callable[[dict], NodeStream]] = getattr(executor, "stream", None)

    @staticmethod
    def _to_node_func(executor: Callable | LLMClient) -> Callable[[dict], dict]:
        if callable(executor):
            return executor
        raise TypeError("Executor must be callable or LLMClient")

    @property
    def can_stream(self) -> bool:
        return callable(self._stream_func)

    def run(self, state: dict) -> dict:
        update = self._func(state)
        if update is None:
            return {}
        if not isinstance(update, dict):
            raise TypeError(f"Node '{self.name}' must return dict, got {type(update)}")
        return update

    def stream(self, state: dict) -> NodeStream:
        if not self.can_stream:
            raise TypeError(f"Узел '{self.name}' не поддерживает стримминг")
        return self._stream_func(state)
