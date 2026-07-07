from abc import ABC, abstractmethod


class Executable(ABC):
    @abstractmethod
    def run(self, *args, **kwargs):
        ...
