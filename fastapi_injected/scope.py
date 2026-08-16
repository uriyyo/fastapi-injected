from collections import ChainMap
from collections.abc import AsyncIterator, Iterator, MutableMapping
from contextlib import (
    AbstractContextManager,
    AsyncExitStack,
    asynccontextmanager,
    contextmanager,
)
from contextvars import ContextVar
from dataclasses import field, replace
from typing import Any, Self, cast

from fastapi import FastAPI, Request
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute, APIWebSocketRoute
from starlette.types import Message, Scope

from ._cache import ScopeCache, overridden_calls
from ._dataclass import MakeDataclass
from ._overrides import Overrides, normalize_overrides
from ._rlock import RLock
from .types import DependencyCache, HasDependencyOverrides


class UnboundScopeError(Exception):
    def __init__(self) -> None:
        super().__init__("Scope is not bound to a request")


_SYNTHETIC_REQUEST_KEY = "__fastapi_injected_synthetic_request__"


class _SyntheticScope(dict[str, Any]):
    def __missing__(self, key: str) -> Any:
        raise KeyError(
            f"{key!r} is not part of a synthetic request - "
            f"pass request= (or app=) to push_inject_scope() to resolve against a real one",
        )


def _dummy_scope() -> Scope:
    return _SyntheticScope(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "server": None,
            "client": None,
            "root_path": "",
            "path": "/",
            "raw_path": b"/",
            "query_string": b"",
            "headers": [],
            "path_params": {},
            _SYNTHETIC_REQUEST_KEY: True,
        },
    )


def _dummy_request(
    *,
    app: FastAPI | None = None,
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

    if app is not None:
        scope["app"] = app

    if extra_scope:
        scope.update(extra_scope)

    return Request(
        scope,
        receive=_dummy_receive,
        send=_dummy_send,
    )


def _rebind_request(
    request: Request,
    /,
    *,
    extra_scope: Scope,
) -> Request:
    scope = {**request.scope, **extra_scope}

    return Request(
        scope,
        receive=request.receive,
        send=request._send,  # noqa: SLF001
    )


class InjectScope(MakeDataclass):
    dependency_cache: DependencyCache = field(default_factory=dict)
    request: Request | None = None

    parent: Self | None = field(default=None, repr=False)
    overrides: MutableMapping[Any, Any] = field(default_factory=dict, repr=False)
    inherit_cache: bool = field(default=False, repr=False)
    lock: RLock = field(default_factory=RLock, repr=False)

    @classmethod
    def current(cls) -> Self | None:
        return cast(Self | None, _inject_scope.get())

    @property
    def bound(self) -> bool:
        return self.request is not None

    @property
    def bound_request(self) -> Request:
        if self.request is None:
            raise UnboundScopeError

        return self.request

    @property
    def scopes(self) -> Iterator[Self]:
        scope: Self | None = self

        while scope is not None:
            yield scope
            scope = scope.parent

    @property
    def dependency_overrides(self) -> MutableMapping[Any, Any]:
        # the innermost scope wins, and every scope it is nested in is a fallback
        return ChainMap(*[scope.overrides for scope in self.scopes])

    @property
    def path_format(self) -> str | None:
        match self.request.scope if self.request is not None else None:
            case {"route": APIRoute() | APIWebSocketRoute() as route}:
                return route.path_format
            case _:
                return None

    @property
    def synthetic(self) -> bool:
        if self.request is None:
            return True

        return bool(self.request.scope.get(_SYNTHETIC_REQUEST_KEY, False))

    @property
    def cache_scopes(self) -> Iterator[Self]:
        scope = self

        while scope.inherit_cache and scope.parent is not None:
            scope = scope.parent
            yield scope

    def cache_for(self, dependant: Dependant, /) -> ScopeCache:
        fallbacks = []
        introduced: set[Any] = set(self.overrides)

        # an outer scope resolved under the overrides it could see, so only the ones
        # pushed after it invalidate what it has cached
        for scope in self.cache_scopes:
            fallbacks.append((scope.dependency_cache, overridden_calls(dependant, introduced)))
            introduced |= set(scope.overrides)

        return ScopeCache(self.dependency_cache, fallbacks)

    def override(
        self,
        overrides: Overrides | None = None,
        /,
        *,
        provider: HasDependencyOverrides | None = None,
    ) -> AbstractContextManager[Self]:
        return _push_scope(
            replace(
                self,
                parent=self,
                dependency_cache={},
                inherit_cache=True,
                overrides=normalize_overrides(overrides, provider=provider),
            ),
        )


_inject_scope: ContextVar[InjectScope | None] = ContextVar(
    "_inject_scope",
    default=None,
)


@contextmanager
def _push_scope[S: InjectScope](scope: S, /) -> Iterator[S]:
    token = _inject_scope.set(scope)

    try:
        yield scope
    finally:
        _inject_scope.reset(token)


@asynccontextmanager
async def push_inject_scope(
    overrides: Overrides | None = None,
    /,
    *,
    dependency_cache: DependencyCache | None = None,
    request: Request | None = None,
    app: FastAPI | None = None,
    provider: HasDependencyOverrides | None = None,
) -> AsyncIterator[InjectScope]:
    if dependency_cache is None:
        dependency_cache = {}

    parent = InjectScope.current()

    # a scope of its own is about building dependencies again, not about leaving the
    # request they are built for
    if request is None and parent is not None:
        request = parent.request

    async with AsyncExitStack() as stack:
        extra_scope: Scope = {
            "fastapi_inner_astack": stack,
            "fastapi_function_astack": stack,
        }

        request = (
            _rebind_request(request, extra_scope=extra_scope)
            if request is not None
            else _dummy_request(app=app, extra_scope=extra_scope)
        )

        scope = InjectScope(
            dependency_cache,
            request,
            parent=parent,
            overrides=normalize_overrides(overrides, provider=provider),
        )

        with _push_scope(scope):
            yield scope


@asynccontextmanager
async def inside_inject_scope(
    *,
    new_scope: bool = False,
) -> AsyncIterator[InjectScope]:
    scope = InjectScope.current()

    async with AsyncExitStack() as stack:
        # a scope that carries only overrides has no request to resolve against,
        # so resolution happens in a scope of its own that inherits them
        if scope is None or new_scope or not scope.bound:
            scope = await stack.enter_async_context(push_inject_scope())

        yield scope


__all__ = [
    "InjectScope",
    "UnboundScopeError",
    "inside_inject_scope",
    "push_inject_scope",
]
