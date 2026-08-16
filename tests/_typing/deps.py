from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass

from ty_extensions import static_assert
from ty_extensions._internal import (
    CallableTypeOf,
    TypeOf,
    is_assignable_to,
    is_equivalent_to,
    is_subtype_of,
)

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


def sync_ctx_dep() -> Iterator[ContextState]:
    state = ContextState()
    try:
        yield state
    finally:
        state.closed = True


async def coro_ctx_dep() -> ContextState:
    return ContextState()


def get_value() -> int:
    return 1


class NonPydanticType:
    def __init__(self, value: int) -> None:
        self.value = value


__all__ = [
    "CallableTypeOf",
    "Child",
    "Container",
    "ContextState",
    "NonPydanticType",
    "TypeOf",
    "coro_ctx_dep",
    "ctx_dep",
    "get_value",
    "is_assignable_to",
    "is_equivalent_to",
    "is_subtype_of",
    "static_assert",
    "sync_ctx_dep",
]
