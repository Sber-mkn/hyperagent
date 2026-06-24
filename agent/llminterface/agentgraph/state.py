from typing import Annotated, Any, TypedDict
import operator


def add_messages(old: list, new: list) -> list:
    if not isinstance(new, list):
        new= [new]
    return (old or []) + new


def replace(old: Any, new: Any) -> Any:
    return new

class AgentState(TypedDict, total=False):
    messages: Annotated[list, add_messages]
    input: Annotated[str, replace]
    output: Annotated[str, replace]
    thinking: Annotated[str, replace]
    step: Annotated[int, operator.add]


def merge_state(state: dict, update: dict, schema: type) -> dict:
    """Вкладывание update в state, применяя reducer из аннотаций схемы"""
    hints = getattr(schema, "__annotations__", {})
    new_state = dict(state)

    for key, value in update.items():
        annotation = hints.get(key)
        reducer = replace

        if annotation is not None and hasattr(annotation, "__metadata__"):
            reducer = annotation.__metadata__[0]
        if key in new_state:
            new_state[key] = reducer(new_state[key], value)
        else:
            # первый раз: для аккумулирующих reducer'ов нужна «пустая база»
            new_state[key] = reducer(_empty_for(reducer), value) \
                if reducer in (add_messages, operator.add) else value

    return new_state


def _empty_for(reducer) -> Any:
    if reducer is add_messages:
        return []
    if reducer is operator.add:
        return 0
    return None