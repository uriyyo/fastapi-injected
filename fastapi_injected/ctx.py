from __future__ import annotations

import json
from collections import ChainMap
from collections.abc import AsyncGenerator, Generator, Iterator, Mapping, MutableMapping, Sequence
from contextlib import (
    AbstractContextManager,
    AsyncExitStack,
    asynccontextmanager,
    contextmanager,
)
from contextvars import ContextVar, Token
from dataclasses import dataclass, field, replace
from types import TracebackType
from typing import Any, Self, cast
from urllib.parse import urlencode

from anyio import CancelScope
from fastapi import FastAPI, Request, WebSocket
from fastapi.dependencies.models import Dependant
from fastapi.encoders import jsonable_encoder
from fastapi.routing import APIRoute, APIWebSocketRoute
from starlette.datastructures import FormData
from starlette.requests import HTTPConnection
from starlette.types import Message, Scope
from starlette.websockets import WebSocketState
from typing_extensions import sentinel

from ._body import BODY_CACHE_KEY
from ._cache import ContextCache, overridden_calls
from ._dataclass import MakeDataclass
from ._overrides import Overrides, normalize_overrides
from ._rlock import RLock
from .types import BoundConnection, DependencyCache, HasDependencyOverrides


class UnboundContextError(Exception):
    def __init__(self) -> None:
        super().__init__("Injection context is not bound to a request")


_SYNTHETIC_REQUEST_KEY = "__fastapi_injected_synthetic_request__"


class _SyntheticScope(dict[str, Any]):
    def __missing__(self, key: str) -> Any:
        raise KeyError(
            f"{key!r} is not part of a synthetic request - "
            f"pass request= (or app=) to injection_ctx() to resolve against a real one",
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


def _raw_body(body: Any, /) -> tuple[bytes, str | None]:
    match body:
        case None:
            return b"", None
        case bytes():
            return body, None
        case str():
            return body.encode(), None
        case _:
            return json.dumps(jsonable_encoder(body)).encode(), "application/json"


def _raw_headers(
    headers: Mapping[str, str],
    cookies: Mapping[str, str],
    /,
    *,
    content_type: str | None,
) -> list[tuple[bytes, bytes]]:
    raw = {key.lower(): value for key, value in headers.items()}

    if content_type is not None:
        raw.setdefault("content-type", content_type)

    if cookies:
        raw["cookie"] = "; ".join(f"{key}={value}" for key, value in cookies.items())

    return [(key.encode("latin-1"), value.encode("latin-1")) for key, value in raw.items()]


def _dummy_request(
    *,
    app: FastAPI | None = None,
    body: bytes = b"",
    extra_scope: Scope | None = None,
) -> Request:
    async def _dummy_receive() -> Message:
        return {
            "type": "http.request",
            "body": body,
        }

    async def _dummy_send(_: Message, /) -> None:
        pass

    scope = _dummy_scope()
    scope[BODY_CACHE_KEY] = {}

    if app is not None:
        scope["app"] = app

    if extra_scope:
        scope.update(extra_scope)

    return Request(
        scope,
        receive=_dummy_receive,
        send=_dummy_send,
    )


class _ReboundWebSocket(WebSocket):
    def __init__(self, origin: WebSocket, /, *, scope: Scope) -> None:
        HTTPConnection.__init__(self, scope)

        self._origin = origin
        self._receive = origin._receive  # noqa: SLF001
        self._send = origin._send  # noqa: SLF001

    @property
    def client_state(self) -> WebSocketState:
        return self._origin.client_state

    @client_state.setter
    def client_state(self, state: WebSocketState) -> None:
        self._origin.client_state = state

    @property
    def application_state(self) -> WebSocketState:
        return self._origin.application_state

    @application_state.setter
    def application_state(self, state: WebSocketState) -> None:
        self._origin.application_state = state


class _ReboundRequest(Request):
    def __init__(self, origin: Request, /, *, scope: Scope) -> None:
        super().__init__(scope, receive=origin.receive, send=origin._send)  # noqa: SLF001

        self._origin = origin

    async def stream(self) -> AsyncGenerator[bytes]:
        async for chunk in self._origin.stream():
            yield chunk

    async def body(self) -> bytes:
        return await self._origin.body()

    async def json(self) -> Any:
        return await self._origin.json()

    async def _get_form(self, **kwargs: Any) -> FormData:
        return await self._origin._get_form(**kwargs)  # noqa: SLF001

    async def close(self) -> None:
        await self._origin.close()


def synthetic_request(  # noqa: PLR0913
    *,
    app: FastAPI | None = None,
    headers: Mapping[str, str] | None = None,
    query_params: Mapping[str, str | Sequence[str]] | None = None,
    cookies: Mapping[str, str] | None = None,
    path_params: Mapping[str, Any] | None = None,
    body: Any = None,
) -> Request:
    raw_body, content_type = _raw_body(body)

    return _dummy_request(
        app=app,
        body=raw_body,
        extra_scope={
            "headers": _raw_headers(headers or {}, cookies or {}, content_type=content_type),
            "query_string": urlencode(query_params or {}, doseq=True).encode("latin-1"),
            "path_params": dict(path_params or {}),
        },
    )


def _rebind_request(
    request: BoundConnection,
    /,
    *,
    extra_scope: Scope,
) -> BoundConnection:
    # shared by every context of the request
    request.scope.setdefault(BODY_CACHE_KEY, {})

    scope = {**request.scope, **extra_scope}

    if isinstance(request, WebSocket):
        return _ReboundWebSocket(request, scope=scope)

    return _ReboundRequest(request, scope=scope)


class InjectionContext(MakeDataclass):
    dependency_cache: DependencyCache = field(default_factory=dict)
    request: BoundConnection | None = None

    parent: Self | None = field(default=None, repr=False)
    own_overrides: MutableMapping[Any, Any] = field(default_factory=dict, repr=False)
    inherit_cache: bool = field(default=False, repr=False)
    lock: RLock = field(default_factory=RLock, repr=False)
    state: dict[ContextValue[Any], Any] = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def current(cls) -> Self | None:
        return cast(Self | None, _injection_ctx.get())

    @property
    def bound(self) -> bool:
        return self.request is not None

    @property
    def bound_request(self) -> BoundConnection:
        if self.request is None:
            raise UnboundContextError

        return self.request

    @property
    def chain(self) -> Iterator[Self]:
        ctx: Self | None = self

        while ctx is not None:
            yield ctx
            ctx = ctx.parent

    @property
    def dependency_overrides(self) -> MutableMapping[Any, Any]:
        # the innermost context wins, and every context it is nested in is a fallback
        return ChainMap(*[ctx.own_overrides for ctx in self.chain])

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
    def inherited_cache_ctxs(self) -> Iterator[Self]:
        ctx = self

        while ctx.inherit_cache and ctx.parent is not None:
            ctx = ctx.parent
            yield ctx

    def cache_for(self, dependant: Dependant, /) -> ContextCache:
        fallbacks = []
        introduced: set[Any] = set(self.own_overrides)

        # an outer context resolved under the overrides it could see, so only the ones
        # pushed after it invalidate what it has cached
        for ctx in self.inherited_cache_ctxs:
            fallbacks.append((ctx.dependency_cache, overridden_calls(dependant, introduced)))
            introduced |= set(ctx.own_overrides)

        return ContextCache(self.dependency_cache, fallbacks)

    def override(
        self,
        overrides: Overrides | None = None,
        /,
        *,
        provider: HasDependencyOverrides | None = None,
    ) -> OverrideBlock[Self]:
        return OverrideBlock(
            replace(
                self,
                parent=self,
                dependency_cache={},
                state={},
                inherit_cache=True,
                own_overrides=normalize_overrides(overrides, provider=provider),
            ),
        )


class NoInjectionContextError(LookupError):
    def __init__(self) -> None:
        super().__init__("no injection context is open")


MISSING = sentinel("MISSING")


@dataclass(frozen=True, eq=False)
class ContextValue[T]:
    name: str
    default: T | MISSING = field(default=MISSING, kw_only=True)

    def get(self) -> T:
        if (ctx := InjectionContext.current()) is not None:
            for owner in ctx.chain:
                if self in owner.state:
                    return owner.state[self]

        if self.default is MISSING:
            raise LookupError(f"{self.name} is not set")

        return self.default

    def set(self, value: T, /) -> None:
        if (ctx := InjectionContext.current()) is None:
            raise NoInjectionContextError

        ctx.state[self] = value


@contextmanager
def _reset_on_exit[T](var: ContextVar[T], token: Token[T], value: T, /) -> Generator[T]:
    try:
        yield value
    finally:
        var.reset(token)


def set_var[T](var: ContextVar[T], value: T, /) -> AbstractContextManager[T]:
    # set right away; `with` also puts the previous value back
    return _reset_on_exit(var, var.set(value), value)


_injection_ctx: ContextVar[InjectionContext | None] = ContextVar(
    "_injection_ctx",
    default=None,
)


_default_app: ContextVar[FastAPI | None] = ContextVar("_default_app", default=None)


def set_default_app(app: FastAPI | None, /) -> AbstractContextManager[FastAPI | None]:
    return set_var(_default_app, app)


def _scope_app(request: BoundConnection | None, /) -> HasDependencyOverrides | None:
    match request.scope.get("app") if request is not None else None:
        case HasDependencyOverrides() as app:
            return app
        case _:
            return None


def _with_stack(
    request: BoundConnection | None,
    stack: AsyncExitStack,
    /,
    *,
    app: FastAPI | None = None,
) -> BoundConnection:
    # what is built against the returned request is torn down with `stack`
    extra_scope: Scope = {
        "fastapi_inner_astack": stack,
        "fastapi_function_astack": stack,
        "fastapi_async_cleanup_scopes": {
            stack: stack.enter_context(CancelScope()),
        },
    }

    request = (
        _rebind_request(request, extra_scope=extra_scope)
        if request is not None
        else _dummy_request(app=app, extra_scope=extra_scope)
    )

    request.scope.setdefault("fastapi_middleware_astack", stack)

    return request


@dataclass
class OverrideBlock[S: InjectionContext]:
    ctx: S

    _entered: AbstractContextManager[InjectionContext | None] | None = field(default=None, init=False)
    _stack: AsyncExitStack | None = field(default=None, init=False)

    def __init__(self, ctx: S, /) -> None:
        self.ctx = ctx

    def __enter__(self) -> S:
        self._entered = set_var(_injection_ctx, self.ctx)
        self._entered.__enter__()

        return self.ctx

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
        /,
    ) -> None:
        if self._entered is not None:
            self._entered.__exit__(exc_type, exc, tb)

    async def __aenter__(self) -> S:
        self._stack = stack = AsyncExitStack()
        await stack.__aenter__()

        try:
            ctx = replace(self.ctx, request=_with_stack(self.ctx.request, stack))
            stack.enter_context(set_var(_injection_ctx, ctx))
        except BaseException as exc:
            await stack.__aexit__(type(exc), exc, exc.__traceback__)
            raise

        return ctx

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
        /,
    ) -> bool | None:
        if self._stack is not None:
            return await self._stack.__aexit__(exc_type, exc, tb)

        return None


@asynccontextmanager
async def injection_ctx(
    overrides: Overrides | None = None,
    /,
    *,
    dependency_cache: DependencyCache | None = None,
    request: BoundConnection | None = None,
    app: FastAPI | None = None,
    provider: HasDependencyOverrides | None = None,
) -> AsyncGenerator[InjectionContext]:
    if dependency_cache is None:
        dependency_cache = {}

    parent = InjectionContext.current()

    # the app a context is told about overrides like the app of a route would; one only
    # inherited from the parent already reaches it through the parent's overrides
    if provider is None:
        provider = cast("HasDependencyOverrides", app) if app is not None else _scope_app(request)

    # a context of its own is about building dependencies again, not about leaving the
    # request they are built for
    if request is None and parent is not None:
        request = parent.request

    # no request to take the app from, so the default one stands in
    if request is None and app is None:
        app = _default_app.get()

        if provider is None:
            provider = cast("HasDependencyOverrides | None", app)

    async with AsyncExitStack() as stack:
        request = _with_stack(request, stack, app=app)

        ctx = InjectionContext(
            dependency_cache,
            request,
            parent=parent,
            own_overrides=normalize_overrides(overrides, provider=provider),
        )

        with set_var(_injection_ctx, ctx):
            yield ctx


@asynccontextmanager
async def ensure_injection_ctx(
    *,
    new_ctx: bool = False,
) -> AsyncGenerator[InjectionContext]:
    ctx = InjectionContext.current()

    async with AsyncExitStack() as stack:
        # a context that carries only overrides has no request to resolve against,
        # so resolution happens in a context of its own that inherits them
        if ctx is None or new_ctx or not ctx.bound:
            ctx = await stack.enter_async_context(injection_ctx())

        yield ctx


__all__ = [
    "ContextValue",
    "InjectionContext",
    "NoInjectionContextError",
    "OverrideBlock",
    "UnboundContextError",
    "ensure_injection_ctx",
    "injection_ctx",
    "set_default_app",
    "synthetic_request",
]
