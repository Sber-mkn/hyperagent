from typing import Any, Callable, Dict, List, Optional
from concurrent.futures import ThreadPoolExecutor

from agent.llminterface.agent_chain.executable import Executable, MISSING
from agent.llminterface.agent_graph.agent_state import AgentState


class _End:
    def __repr__(self) -> str:
        return "END"


END = _End()

Router = Callable[[AgentState], Any]


def _as_list(x: Any) -> List[Any]:
    if isinstance(x, (list, tuple, set)):
        return list(x)
    return [x]


class AgentGraph(Executable):

    def __init__(self, max_steps: int = 1000, max_workers: Optional[int] = None):
        self._nodes: Dict[str, Executable] = {}
        self._edges: Dict[str, List[Any]] = {}   # src -> [dst, ...] (dst может быть END)
        self._routers: Dict[str, Router] = {}    # src -> router (условное ребро)
        self._entry: List[str] = []              # один или несколько стартовых узлов
        self._max_steps = max_steps              # защита от бесконечного цикла (в супершагах)
        self._max_workers = max_workers          # потолок потоков на супершаг (None -> по числу узлов)

    # сборка
    def add_node(self, name: str, node: Any) -> "AgentGraph":
        if name in self._nodes:
            raise ValueError(f"Узел '{name}' уже зарегистрирован")
        self._nodes[name] = Executable.to_executable(node)
        return self

    def add_edge(self, src: str, *dst: Any) -> "AgentGraph":
        self._edges.setdefault(src, []).extend(dst)
        return self

    def add_conditional_edge(self, src: str, router: Router) -> "AgentGraph":
        self._routers[src] = router
        return self

    def set_entry(self, *names: str) -> "AgentGraph":
        self._entry = list(names)
        return self

    def _successors(self, node: str, state: AgentState) -> List[Any]:
        if node in self._routers:
            return _as_list(self._routers[node](state))    # условное ребро приоритетнее
        return _as_list(self._edges.get(node, [END]))      # нет ребра -> конец

    def _run_frontier(self, frontier: List[str], state: AgentState, method: str) -> List[Any]:
        for name in frontier:
            if name not in self._nodes:
                raise KeyError(f"Узел '{name}' не зарегистрирован")

        if len(frontier) == 1:                               # один узел — без пула
            return [getattr(self._nodes[frontier[0]], method)(state)]

        workers = self._max_workers or len(frontier)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [
                pool.submit(getattr(self._nodes[name], method), state)
                for name in frontier
            ]
            return [f.result() for f in futures]

    # исполнение
    def _drive(self, _input: Any, method: str) -> AgentState:
        """Общий обход. `method` — "run" или "stream": этим методом дёргается
        каждый узел (stream-дорожка доходит до .stream() у вложенных узлов)."""
        if not self._entry:
            raise ValueError("Не задан входной узел (set_entry)")

        state = _input if isinstance(_input, AgentState) else AgentState()
        frontier: List[str] = list(dict.fromkeys(self._entry))   # dedup, порядок сохранён
        steps = 0

        while frontier:
            if steps >= self._max_steps:
                raise RuntimeError(
                    f"Превышен лимит шагов графа ({self._max_steps}) — вероятно, цикл"
                )

            updates = self._run_frontier(frontier, state, method)

            for upd in updates:
                if isinstance(upd, AgentState):
                    state = upd
                elif isinstance(upd, dict):
                    state.merge(upd)

            nxt: List[str] = []
            for name in frontier:
                for succ in self._successors(name, state):
                    if succ is not END:
                        nxt.append(succ)
            frontier = list(dict.fromkeys(nxt))
            steps += 1

        return state

    def run(self, _input: Any = MISSING) -> AgentState:
        return self._drive(_input, "run")

    def stream(self, _input: Any = MISSING) -> AgentState:
        return self._drive(_input, "stream")
