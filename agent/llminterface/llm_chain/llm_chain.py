from __future__ import annotations

from typing import Callable, Any, Dict, Optional



class Unit:
    _func: Callable[..., Any]
    _parameters: Dict[str, Any]

    def __init__(self, func: Callable[..., Any], **kwargs):
        self._func = func
        self._parameters = kwargs

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        temp_kwargs = {**self._parameters, **kwargs}
        return self._func(*args, **temp_kwargs)


class GraphNode:
    _func: Unit | Callable[..., Any]
    _input: Optional[str] = None
    _output: Optional[str] = None

    def __init__(
            self,
            _func: Unit | Callable[..., Any],
            _input: Optional[str] = None,
            _output: Optional[str] = None,
            children: Optional[list[GraphNode]] = None
    ):
        self._func = _func
        self._input = _input
        self._output = _output
        self.children = children if children is not None else []

    @staticmethod
    def _normalize_right(value) -> tuple[Optional[str], Callable[..., Any], Optional[str]]:
        if callable(value):
            return None, value, None

        if isinstance(value, tuple):
            items = list(value)
            func_positions = [i for i, x in enumerate(items) if callable(x)]

            if len(func_positions) != 1:
                raise ValueError(
                    f"Ожидается ровно один callable в кортеже, получено {len(func_positions)}: {value!r}"
                )

            func_idx = func_positions[0]
            func = items[func_idx]
            before = items[:func_idx]
            after = items[func_idx + 1:]

            _input = before[0] if before else None
            _output = after[0] if after else None
            return _input, func, _output

        raise TypeError(f"Недопустимый тип {type(value).__name__} в (input, func, output)")

    @staticmethod
    def start() -> GraphNode:
        def func():
            pass
        return GraphNode(func)

    def __call__(self, dict_: Optional[dict] = None) -> dict:
        if dict_ is None:
            dict_ = {}
        if self._input is not None:
            output = self._func(dict_[self._input])
        else:
            output = self._func()
        if self._output is not None:
            dict_[self._output] = output


        for child in self.children:
            child(dict_)
        return dict_

    def __rshift__(
            self,
            value: Callable[..., Any] |
                   tuple[str, Callable[..., Any]] |
                   tuple[Callable[..., Any], str] |
                   tuple[str, Callable[..., Any], str] |
                   GraphNode
    ) -> GraphNode:
        if isinstance(value, GraphNode):
            new_node = value
        else:
            _input, func, _output = self._normalize_right(value)
            new_node = GraphNode(func, _input, _output)
        self.children.append(new_node)

        return new_node

    def __or__(
            self,
            value: Callable[..., Any] |
                   tuple[str, Callable[..., Any]] |
                   tuple[Callable[..., Any], str] |
                   tuple[str, Callable[..., Any], str] |
                   GraphNode
    ) -> GraphNode:
        if isinstance(value, GraphNode):
            new_node = value
        else:
            _input, func, _output = self._normalize_right(value)
            new_node = GraphNode(func, _input, _output)
        self.children.append(new_node)

        return self


# UserInput: Callable, field: str  >> LLMClient: Callable, field: str >> StrOutput