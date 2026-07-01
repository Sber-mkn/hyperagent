from agent.llminterface.agent_chain.executable import Executable, MISSING
from typing import List, Any, Callable
from functools import partial

class ExecSequence(Executable):

    def __init__(self, *nodes: Executable):
        self._nodes: List[Executable] = []

        for node in nodes:
            if isinstance(node, ExecSequence):
                self._nodes.extend(node._nodes)
            else:
                self._nodes.append(node)

    def run(self, _input: Any = MISSING):
        first = _input is MISSING
        result = _input
        for node in self._nodes:
            if first:
                result = node.run()
                first = False
            else:
                result = node.run(result)
        return result


    def stream(self, _input: Any = MISSING):
        first = _input is MISSING
        result = _input
        for node in self._nodes:
            if first:
                result = node.stream()
                first = False
            else:
                result = node.stream(result)
        return result


class ExecParallel(Executable):
    def __init__(self, branches: dict[str, Any]):
        self._branches = {k: Executable.to_executable(v) for k, v in branches.items()}

    def run(self, _input: Any = MISSING):
        if _input is not MISSING:
            return {k: b.run(_input) for k, b in self._branches.items()}
        else:
            return {k: b.run() for k, b in self._branches.items()}


    def stream(self, _input: Any = MISSING):
        if _input is not MISSING:
            return {k: b.stream(_input) for k, b in self._branches.items()}
        else:
            return {k: b.run() for k, b in self._branches.items()}


class ExecLambda(Executable):
    def __init__(self, func: Callable[..., Any]):
        self._func = func

    def run(self, _input: Any = MISSING):
        return self._func(_input) if _input is not MISSING else self._func()

    def stream(self, _input: Any = MISSING):
        return self.run(_input)


class ExecPassthrough(Executable):
    def run(self, _input: Any = MISSING):
        return _input


class ExecPartial(Executable):
    def __init__(self, _exec: Any, *args, **kwargs):
        self._exec = Executable.to_executable(partial(_exec, *args, **kwargs))

    def run(self, _input: Any = MISSING):
        if _input is not MISSING:
            return self._exec.run(_input)
        return self._exec.run()


class ExecMultiargument(Executable):
    def __init__(self, _target: Callable[..., Any] | Executable):
        self._target = _target

    def _call(self, method: str, _input: Any = MISSING):
        if isinstance(self._target, Executable):
            func = getattr(self._target, method)
        elif callable(self._target):
            func = self._target
        else:
            raise TypeError(
                f"{type(self._target)} нельзя вызывать через ExecMultiargument"
            )

        if isinstance(_input, dict):
            return func(**_input)
        if isinstance(_input, tuple):
            return func(*_input)
        return func(_input)

    def run(self, _input: Any = MISSING):
        return self._call("run", _input)

    def stream(self, _input: Any = MISSING):
        method = "stream" if isinstance(self._target, Executable) else "__call__"
        return self._call(method, _input)


class ExecSelect(Executable):
    def __init__(self, **mapping: str):
        self._mapping = mapping

    def run(self, _input: Any = MISSING):
        return {new: _input[src] for new, src in self._mapping.items()}

    def stream(self, _input: Any = MISSING):
        return self.run(_input)


class ExecEffect(Executable):
    def __init__(self, effect: Any):
        self._effect = Executable.to_executable(effect)

    def run(self, _input: Any = MISSING):
        self._effect.run(_input)
        return _input

    def stream(self, _input: Any = MISSING):
        self._effect.stream(_input)
        return _input


class ExecCall(Executable):
    def __init__(self, target: Any = MISSING):
        self._target = target

    def run(self, _input: Any = MISSING):
        if isinstance(self._target, Executable):
            return self._target.run()
        return self._target()

    def stream(self, _input: Any = MISSING):
        if isinstance(self._target, Executable):
            return self._target.stream()
        return self._target()