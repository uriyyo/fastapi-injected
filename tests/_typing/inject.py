from collections.abc import Callable, Coroutine
from typing import Any

from fastapi_injected import Dep, DepFactory, Injected, inject

from .deps import (
    Child,
    Container,
    ContextState,
    TypeOf,
    ctx_dep,
    is_assignable_to,
    is_equivalent_to,
    static_assert,
)


@inject
async def handler(
    a: int,
    b: str = "b",
    *,
    container: Dep[Container] = Injected,
    ctx: DepFactory[ContextState, ctx_dep] = Injected,
) -> int:
    # injected parameters are typed as the dependency they resolve to, all the way down
    static_assert(is_equivalent_to(TypeOf[container], Container))
    static_assert(is_equivalent_to(TypeOf[container.child], Child))
    static_assert(is_equivalent_to(TypeOf[container.ctx], ContextState))
    static_assert(is_equivalent_to(TypeOf[ctx], ContextState))

    return a + len(b)


# the parametrized form is a decorator, so it produces the very same function type
@inject(new_scope=True)
async def handler_new_scope(*, container: Dep[Container] = Injected) -> Container:
    return container


# decorating keeps the signature, injected parameters included
static_assert(is_assignable_to(TypeOf[handler_new_scope], Callable[[], Coroutine[Any, Any, Container]]))


async def _calls() -> None:
    # own arguments are passed as usual, injected ones are filled in by the decorator
    static_assert(is_equivalent_to(TypeOf[await handler(1)], int))
    static_assert(is_equivalent_to(TypeOf[await handler(1, "b")], int))
    static_assert(is_equivalent_to(TypeOf[await handler_new_scope()], Container))

    # ... and nothing stops passing them explicitly
    static_assert(is_equivalent_to(TypeOf[await handler(1, container=Container(Child(), ContextState()))], int))


async def _negatives() -> None:
    await handler()  # type: ignore[ty:missing-argument]
    await handler("1")  # type: ignore[ty:invalid-argument-type]
    await handler(1, container=Child())  # type: ignore[ty:invalid-argument-type]
    await handler(1, unknown=1)  # type: ignore[ty:unknown-argument]

    inject(new_scope="yes")  # type: ignore[ty:invalid-argument-type]

    # the wrapper awaits what it decorates, so sync functions are rejected by both forms
    @inject  # type: ignore[ty:invalid-argument-type]
    def _sync(*, container: Dep[Container] = Injected) -> None:
        pass

    @inject(new_scope=True)  # type: ignore[ty:invalid-argument-type]
    def _sync_new_scope(*, container: Dep[Container] = Injected) -> None:
        pass
