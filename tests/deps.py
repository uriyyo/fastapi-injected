from collections.abc import AsyncIterator
from dataclasses import dataclass

from fastapi_injected import Dep, DepFactory


@dataclass
class ContextState:
    closed: bool = False


async def ctx_dep() -> AsyncIterator[ContextState]:
    state = ContextState()
    try:
        yield state
    finally:
        state.closed = True


@dataclass
class Child:
    pass


@dataclass
class Container:
    child: Dep[Child]
    ctx: DepFactory[ContextState, ctx_dep]


def get_value() -> int:
    return 1


@dataclass
class State:
    value: DepFactory[int, get_value]


__all__ = [
    "Child",
    "Container",
    "ContextState",
    "State",
    "ctx_dep",
]
