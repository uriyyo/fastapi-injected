from collections.abc import AsyncGenerator, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from functools import cache, wraps
from typing import Any, Protocol, cast, runtime_checkable

from fastapi import FastAPI, Request, Response, WebSocket, routing
from fastapi.dependencies import utils
from fastapi.dependencies.models import Dependant
from fastapi.dependencies.utils import get_dependant
from fastapi.exception_handlers import (
    request_validation_exception_handler,
    websocket_request_validation_exception_handler,
)
from fastapi.exceptions import WebSocketRequestValidationError
from starlette.applications import Starlette
from starlette.requests import HTTPConnection
from starlette.routing import Router
from starlette.types import ASGIApp, ExceptionHandler, Lifespan, Message, Receive, Scope, Send

from ._cache import ContextCache
from ._errors import InjectedError
from ._fastapi_compat import INNER_ASTACK_KEY, patch_fastapi, solve_generator
from .ctx import injection_ctx, set_default_app
from .deps import DependencyResolutionError
from .types import BoundConnection, DependencyCache, HasDependencyOverrides

_DEPENDENCY_CACHE_KEY = "__fastapi_injected_dependency_cache__"
_BOUND_KEY = "__fastapi_injected_bound__"


class MissingDependencyCacheError(InjectedError):
    pass


class ConnectionNotAvailableError(InjectedError):
    def __init__(self) -> None:
        super().__init__("The connection can not be received from or sent to outside of a route")


async def _unavailable_receive() -> Message:
    raise ConnectionNotAvailableError


async def _unavailable_send(_: Message) -> None:
    raise ConnectionNotAvailableError


def _patched_solve_dependencies(base: Callable[..., Any], /) -> Callable[..., Any]:
    @wraps(base)
    async def _solve_dependencies(
        *,
        request: Request | WebSocket,
        dependency_cache: DependencyCache | None = None,
        **kwargs: Any,
    ) -> utils.SolvedDependency:
        # a context brought its own cache - it already reads through to the request one,
        # and knows what its overrides make unusable there
        if not isinstance(dependency_cache, ContextCache):
            if (current_cache := request.scope.get(_DEPENDENCY_CACHE_KEY)) is not None:
                dependency_cache = current_cache
            elif dependency_cache is None:
                dependency_cache = {}

            request.scope[_DEPENDENCY_CACHE_KEY] = dependency_cache

            # the first solve of a request under `InjectionMiddleware` binds its context to the route's connection
            if request.scope.get(_BOUND_KEY) is False:
                await solve_generator(
                    dependant=_bind_dependant(),
                    stack=request.scope[INNER_ASTACK_KEY],
                    sub_values={"connection": request},
                    request=request,
                )

        return await base(
            request=request,
            dependency_cache=dependency_cache,
            **kwargs,
        )

    return _solve_dependencies


def install_dependency_cache() -> None:
    for module in (utils, routing):
        patch_fastapi(module, "solve_dependencies", _patched_solve_dependencies)


def _get_dependency_cache(connection: HTTPConnection) -> DependencyCache:
    try:
        return connection.scope[_DEPENDENCY_CACHE_KEY]
    except KeyError:
        raise MissingDependencyCacheError(
            "no dependency cache for this request - call `add_injection(app)`, or add `InjectionMiddleware`",
        ) from None


def _get_overrides_provider(connection: HTTPConnection) -> HasDependencyOverrides | None:
    route = connection.scope.get("route")

    if (provider := getattr(route, "dependency_overrides_provider", None)) is not None:
        return provider

    # a websocket route does not keep the provider it was given - but it is the app
    # the route was added to, which is what the scope of the connection holds
    return connection.scope.get("app")


# annotated as the base class so FastAPI hands over whichever the route has -
# a `Request` in an HTTP route, a `WebSocket` in a websocket one
async def bind_injection_ctx(connection: HTTPConnection) -> AsyncGenerator[None]:
    if not isinstance(connection, Request | WebSocket):  # pragma: no cover
        raise TypeError(f"expected a Request or a WebSocket, got {type(connection).__name__}")

    if connection.scope.get(_BOUND_KEY):
        yield
        return

    connection.scope[_BOUND_KEY] = True

    # the connection of the route: the middleware context, if any, was bound before routing
    async with injection_ctx(
        dependency_cache=_get_dependency_cache(connection),
        request=connection,
        provider=_get_overrides_provider(connection),
    ):
        yield


@cache
def _bind_dependant() -> Dependant:
    return get_dependant(path="", call=bind_injection_ctx)


@dataclass
class InjectionMiddleware:
    app: ASGIApp

    def __post_init__(self) -> None:
        install_dependency_cache()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        connection: BoundConnection

        match scope["type"]:
            case "http":
                connection = Request(scope, _unavailable_receive, _unavailable_send)
            case "websocket":
                connection = WebSocket(scope, _unavailable_receive, _unavailable_send)
            case _:
                await self.app(scope, receive, send)
                return

        scope[_DEPENDENCY_CACHE_KEY] = cache = {}
        scope[_BOUND_KEY] = False

        async with injection_ctx(
            dependency_cache=cache,
            request=connection,
            provider=_get_overrides_provider(connection),
        ):
            await self.app(scope, receive, send)


def _with_injection_middleware(build: Callable[[], ASGIApp], /) -> Callable[[], ASGIApp]:
    @wraps(build)
    def _build() -> ASGIApp:
        return InjectionMiddleware(build())

    return _build


async def dependency_resolution_handler(connection: HTTPConnection, exc: Exception) -> Response | None:
    unresolved = cast("DependencyResolutionError", exc)

    if isinstance(connection, WebSocket):
        await websocket_request_validation_exception_handler(
            connection,
            WebSocketRequestValidationError(unresolved.errors),
        )
        return None

    return await request_validation_exception_handler(
        cast("Request", connection),
        unresolved.as_validation_error(),
    )


def add_injection(
    app: FastAPI,
    /,
    *,
    handle_resolution_errors: bool = True,
) -> None:
    install_dependency_cache()
    set_default_app(app)

    patch_fastapi(app, "build_middleware_stack", _with_injection_middleware)

    if handle_resolution_errors and DependencyResolutionError not in app.exception_handlers:
        app.add_exception_handler(DependencyResolutionError, cast("ExceptionHandler", dependency_resolution_handler))


@runtime_checkable
class _HasRouter(Protocol):
    router: Router


def add_lifespan(root: Router | Starlette, lifespan: Lifespan[Any], /) -> None:
    match root:
        case Router():
            router = root
        case _HasRouter(router=router):
            pass
        case _:
            raise TypeError(f"{root!r} has no router to attach a lifespan to")

    outer = router.lifespan_context

    @asynccontextmanager
    async def merged(app: Any) -> AsyncGenerator[Mapping[str, Any] | None]:
        async with outer(app) as outer_state, lifespan(app) as inner_state:
            if outer_state is None and inner_state is None:
                yield None
            else:
                yield {
                    **(outer_state or {}),
                    **(inner_state or {}),
                }

    router.lifespan_context = cast(Lifespan[Any], merged)


__all__ = [
    "ConnectionNotAvailableError",
    "InjectionMiddleware",
    "MissingDependencyCacheError",
    "add_injection",
    "add_lifespan",
    "bind_injection_ctx",
    "dependency_resolution_handler",
    "install_dependency_cache",
]
