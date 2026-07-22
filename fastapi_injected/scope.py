from collections.abc import AsyncIterator
from contextlib import (
    AbstractAsyncContextManager,
    AsyncExitStack,
    asynccontextmanager,
    nullcontext,
)
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from .types import DependencyCache


@dataclass
class InjectScope:
    dependency_cache: DependencyCache
    func_astack: AsyncExitStack
    request_astack: AsyncExitStack


_inject_scope: ContextVar[InjectScope | None] = ContextVar(
    "_inject_scope",
    default=None,
)


@asynccontextmanager
async def push_inject_scope(
    dependency_cache: DependencyCache | None = None,
) -> AsyncIterator[InjectScope]:
    async with AsyncExitStack() as stack:
        scope = InjectScope(
            dependency_cache or {},
            stack,
            stack,
        )
        token = _inject_scope.set(scope)

        try:
            yield scope
        finally:
            _inject_scope.reset(token)


def current_inject_scope() -> InjectScope | None:
    return _inject_scope.get()


@asynccontextmanager
async def inside_inject_scope(
    *,
    new_scope: bool = False,
) -> AsyncIterator[InjectScope]:
    scope = current_inject_scope()

    _ctx: AbstractAsyncContextManager[Any]

    if scope is None or new_scope:
        stack = AsyncExitStack()
        scope = await stack.enter_async_context(push_inject_scope())

        _ctx = stack
    else:
        _ctx = nullcontext()

    async with _ctx:
        yield scope


__all__ = [
    "InjectScope",
    "current_inject_scope",
    "inside_inject_scope",
]
