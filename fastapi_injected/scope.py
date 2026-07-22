from collections.abc import AsyncIterator
from contextlib import (
    AsyncExitStack,
    asynccontextmanager,
)
from contextvars import ContextVar
from dataclasses import dataclass

from fastapi import Request
from starlette.types import Message, Scope

from .types import DependencyCache


def _dummy_scope() -> Scope:
    return {
        "type": "http",
        "http_version": "1.1",
        "query_string": b"",
        "headers": [],
    }


def _dummy_request(
    *,
    extra_scope: Scope | None = None,
) -> Request:
    async def _dummy_receive() -> Message:
        return {
            "type": "http.request",
            "body": b"",
        }

    async def _dummy_send(_: Message, /) -> None:
        pass

    scope = _dummy_scope()
    if extra_scope:
        scope.update(extra_scope)

    return Request(
        scope,
        receive=_dummy_receive,
        send=_dummy_send,
    )


@dataclass
class InjectScope:
    dependency_cache: DependencyCache
    request: Request


_inject_scope: ContextVar[InjectScope | None] = ContextVar(
    "_inject_scope",
    default=None,
)


@asynccontextmanager
async def push_inject_scope(
    *,
    dependency_cache: DependencyCache | None = None,
    request: Request | None = None,
) -> AsyncIterator[InjectScope]:
    if dependency_cache is None:
        dependency_cache = {}

    async with AsyncExitStack() as stack:
        request = request or _dummy_request(
            extra_scope={
                "fastapi_inner_astack": stack,
                "fastapi_function_astack": stack,
            },
        )

        scope = InjectScope(dependency_cache, request)
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

    async with AsyncExitStack() as stack:
        if scope is None or new_scope:
            scope = await stack.enter_async_context(push_inject_scope())

        yield scope


__all__ = [
    "InjectScope",
    "current_inject_scope",
    "inside_inject_scope",
]
