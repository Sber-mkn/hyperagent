from agent.llminterface.agentgraph.node import AgentNode
from agent.llminterface.agentgraph.state import merge_state
from agent.llminterface.llm_client import LLMClient

from typing import Callable, Optional, Iterator, Any

START = "__start__"
END = "__end__"


class GraphStream:
    """Обёртка над потоком графа: итерируется по событиям стрима, после
    полного прохода в .state лежит финальное состояние"""

    def __init__(self, generator: Iterator[Any]):
        self._generator = generator
        self.state: Optional[dict] = None

    def __iter__(self) -> Iterator[Any]:
        return self._generator


class AgentGraph:
    def __init__(self, state_schema: type):
        self.schema = state_schema
        self.nodes: dict[str, AgentNode] = {}
        self.edges: dict[str, list[str]] = {}
        self.branches: dict[str, tuple[Callable, Optional[dict]]] = {}
        self.entry_points: list[str] = []
        self._compiled = False

    # Построение графа
    def add_node(self, name: str, executor: Callable | LLMClient) -> "AgentGraph":
        if name in (START, END):
            raise ValueError(f"'{name}' зарезервировано")
        if name in self.nodes:
            raise ValueError(f"Узел '{name}' уже существует")
        self.nodes[name] = AgentNode(name, executor)
        return self

    def add_edge(self, start: str, end: str) -> "AgentGraph":
        if start == START:
            self.entry_points.append(end)
        else:
            self.edges.setdefault(start, []).append(end)
        return self

    def add_conditional_edges(self, start: str, router: Callable[[dict], Any],
                              path_map: Optional[dict[str, str]] = None) -> "AgentGraph":
        self.branches[start] = (router, path_map)
        return self

    def set_entry_point(self, name: str) -> "AgentGraph":
        self.entry_points = [name]
        return self

    def compile(self) -> "AgentGraph":
        if not self.entry_points:
            raise ValueError("Не задана точка входа (add_edge(START, ...))")
        self._compiled = True
        return self


    def _next_nodes(self, current: str, state: dict) -> list[str]:
        targets: list[str] = []
        if current in self.branches:
            router, path_map = self.branches[current]
            result = router(state)
            keys = result if isinstance(result, list) else [result]
            targets += [path_map[k] if path_map else k for k in keys]
        targets += self.edges.get(current, [])
        return targets

    @staticmethod
    def _dedup(names: list[str]) -> list[str]:
        return list(dict.fromkeys(n for n in names if n != END))

    # Параллельное исполнение
    def _run_superstep(self, frontier: list[str], state: dict) -> tuple[dict, list[tuple[str, dict]]]:
        # все узлы читают один state
        updates = [(name, self.nodes[name].run(state)) for name in frontier if name != END]
        new_state = state
        for _, upd in updates:               # fan-in: reducer'ы сливают апдейты вместе
            new_state = merge_state(new_state, upd, self.schema)
        return new_state, updates

    def _advance(self, updates: list[tuple[str, dict]], state: dict) -> list[str]:
        nxt: list[str] = []
        for name, _ in updates:
            nxt += self._next_nodes(name, state)
        return self._dedup(nxt)

    # Запуск
    def run(self, initial_state: dict, recursion_limit: int = 25) -> dict:
        if not self._compiled:
            self.compile()
        state = merge_state({}, dict(initial_state), self.schema)
        frontier = self._dedup(self.entry_points)
        for _ in range(recursion_limit):
            if not frontier:
                return state
            state, updates = self._run_superstep(frontier, state)
            frontier = self._advance(updates, state)
        raise RecursionError(f"Превышен лимит шагов ({recursion_limit})")

    # ───────── Пункт 4: стриминг ─────────
    def stream(self, initial_state: dict, stream_mode: str = "values",
               recursion_limit: int = 25) -> GraphStream:
        """ stream_mode:
        values -> dict полного состояния после каждого super-step
        updates -> (имя_узла, dict-update) по мере выполнения узлов
        messages -> (имя_узла, чанк) для стриминговых узлов (LLMNode)

        После полного прохода итоговое состояние доступно в .state"""
        if not self._compiled:
            self.compile()

        def generator() -> Iterator[Any]:
            state = merge_state({}, dict(initial_state), self.schema)
            frontier = self._dedup(self.entry_points)

            for _ in range(recursion_limit):
                if not frontier:
                    wrapper.state = state
                    return
                updates: list[tuple[str, dict]] = []

                for name in frontier:
                    if name == END:
                        continue
                    node = self.nodes[name]
                    if stream_mode == "messages" and node.can_stream:
                        holder = node.stream(state)
                        for token in holder:
                            yield name, token
                        updates.append((name, holder.update or {}))
                    else:
                        upd = node.run(state)
                        updates.append((name, upd))
                        if stream_mode == "updates":
                            yield name, upd

                new_state = state
                for _, upd in updates:
                    new_state = merge_state(new_state, upd, self.schema)
                state = new_state

                if stream_mode == "values":
                    yield dict(state)

                frontier = self._advance(updates, state)

            wrapper.state = state
            raise RecursionError(f"Превышен лимит шагов ({recursion_limit})")

        wrapper = GraphStream(generator())
        return wrapper
