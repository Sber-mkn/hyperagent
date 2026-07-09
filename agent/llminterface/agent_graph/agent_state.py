from typing import Any, Callable, Dict, Iterator, Optional

Reducer = Callable[[Any, Any], Any]      # (старое, новое) -> итог


class AgentState:
    """Общее изменяемое состояние графа.

    Узлы получают весь state и возвращают частичные обновления (dict),
    которые сливаются сюда через merge(). По ключу можно задать reducer
    (например, добавление в список вместо перезаписи) — тогда несколько
    узлов могут накапливать данные в одном поле.
    """

    def __init__(
            self,
            values: Optional[Dict[str, Any]] = None,
            reducers: Optional[Dict[str, Reducer]] = None,
    ):
        self._values: Dict[str, Any] = dict(values or {})
        self._reducers: Dict[str, Reducer] = dict(reducers or {})

    def __getitem__(self, key: str) -> Any:
        return self._values[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self._values.get(key, default)

    def __contains__(self, key: str) -> bool:
        return key in self._values

    def __iter__(self) -> Iterator[str]:
        return iter(self._values)

    def to_dict(self) -> Dict[str, Any]:
        return dict(self._values)

    def set_reducer(self, key: str, reducer: Reducer) -> "AgentState":
        self._reducers[key] = reducer
        return self

    def merge(self, updates: Dict[str, Any]) -> "AgentState":
        for key, new in updates.items():
            if key in self._reducers and key in self._values:
                self._values[key] = self._reducers[key](self._values[key], new)
            else:
                self._values[key] = new
        return self

    def __repr__(self) -> str:
        return f"AgentState({self._values!r})"
