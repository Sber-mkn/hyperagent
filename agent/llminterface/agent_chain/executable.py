from abc import ABC, abstractmethod

from typing import Any

class _Missing:
    def __repr__(self):
        return "MISSING"

MISSING = _Missing()


class Executable(ABC):

    @staticmethod
    def to_executable(value: Any):
        from agent.llminterface.agent_chain.execs import ExecLambda, ExecParallel
        if isinstance(value, Executable):
            return value
        if callable(value):
            return ExecLambda(value)
        if isinstance(value, dict):
            return ExecParallel(value)
        raise TypeError(
            f"Тип {type(value)} нельзя привести к Executable"
        )

    @abstractmethod
    def run(self, _input: Any = MISSING):
        ...

    def stream(self, _input: Any = MISSING):
        return self.run(_input)


    def __call__(self, _input: Any = MISSING):
        return self.run(_input)

    def __or__(self, other: Any):
        from agent.llminterface.agent_chain.execs import ExecSequence
        return ExecSequence(self, Executable.to_executable(other))

    def __ror__(self, other: Any):
        from agent.llminterface.agent_chain.execs import ExecSequence
        return ExecSequence(Executable.to_executable(other), self)
