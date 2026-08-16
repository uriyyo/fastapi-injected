from typing import Any

from fastapi_injected import Dep, DepFactory, Injected

from .deps import (
    Child,
    Container,
    ContextState,
    TypeOf,
    ctx_dep,
    get_value,
    is_equivalent_to,
    static_assert,
)

# both markers are transparent to type checkers - they are just the annotated type
static_assert(is_equivalent_to(Dep[Container], Container))
static_assert(is_equivalent_to(Dep[int], int))
static_assert(is_equivalent_to(DepFactory[ContextState, ctx_dep], ContextState))
static_assert(is_equivalent_to(DepFactory[int, get_value], int))

# ... which is what makes them usable as regular field annotations
static_assert(is_equivalent_to(TypeOf[Container.child], Child))
static_assert(is_equivalent_to(TypeOf[Container.ctx], ContextState))

# `Injected` is a sentinel default, it fits any annotation
static_assert(is_equivalent_to(TypeOf[Injected], Any))


def _accepts_injected(
    child: Dep[Child] = Injected,
    ctx: DepFactory[ContextState, ctx_dep] = Injected,
    value: int = Injected,
) -> None:
    pass


def _negatives() -> None:
    _: int = Dep[Container]  # type: ignore[ty:invalid-assignment]

    # `DepFactory` needs both the type and the factory
    __: DepFactory[ContextState] = ContextState()  # type: ignore[ty:invalid-type-form]
