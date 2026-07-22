from dataclasses import dataclass
from typing import AsyncIterator

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


__all__ = [
    "Container",
    "ContextState",
    "Child",
    "ctx_dep",
]
