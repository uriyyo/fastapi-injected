import json
from collections import ChainMap
from collections.abc import AsyncGenerator, Generator, Iterator, Mapping, MutableMapping, Sequence
from contextlib import (
    AbstractContextManager,
    AsyncExitStack,
    asynccontextmanager,
    contextmanager,
)
from contextvars import ContextVar
from dataclasses import field, replace
from typing import Any, Self, cast
from urllib.parse import urlencode

from fastapi import FastAPI, Request, WebSocket
from fastapi.dependencies.models import Dependant
from fastapi.encoders import jsonable_encoder
from fastapi.routing import APIRoute, APIWebSocketRoute
from starlette.datastructures import FormData
from starlette.requests import HTTPConnection
from starlette.types import Message, Scope
from starlette.websockets import WebSocketState

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

    @property
    def _form(self) -> FormData | None:
        return self._origin._form  # noqa: SLF001

    @_form.setter
    def _form(self, _: FormData | None) -> None:
        pass

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
    ) -> AbstractContextManager[Self]:
        return _enter_ctx(
            replace(
                self,
                parent=self,
                dependency_cache={},
                inherit_cache=True,
                own_overrides=normalize_overrides(overrides, provider=provider),
            ),
        )


_injection_ctx: ContextVar[InjectionContext | None] = ContextVar(
    "_injection_ctx",
    default=None,
)


@contextmanager
def _enter_ctx[S: InjectionContext](ctx: S, /) -> Generator[S]:
    token = _injection_ctx.set(ctx)

    try:
        yield ctx
    finally:
        _injection_ctx.reset(token)


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

    # a context of its own is about building dependencies again, not about leaving the
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

        request.scope.setdefault("fastapi_middleware_astack", stack)

        ctx = InjectionContext(
            dependency_cache,
            request,
            parent=parent,
            own_overrides=normalize_overrides(overrides, provider=provider),
        )

        with _enter_ctx(ctx):
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
    "InjectionContext",
    "UnboundContextError",
    "ensure_injection_ctx",
    "injection_ctx",
    "synthetic_request",
]
