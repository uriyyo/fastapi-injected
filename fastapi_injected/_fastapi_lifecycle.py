from collections.abc import AsyncGenerator
from dataclasses import dataclass
from functools import wraps
from typing import TYPE_CHECKING, Any

from fastapi import Depends, FastAPI, Request, WebSocket, routing
from fastapi.dependencies import utils
from starlette.requests import HTTPConnection
from starlette.types import ASGIApp, Receive, Scope, Send

from ._cache import ScopeCache
from .scope import push_inject_scope
from .types import BoundConnection, DependencyCache, HasDependencyOverrides

_DEPENDENCY_CACHE_KEY = "__fastapi_injected_dependency_cache__"


class MissingDependencyCacheError(Exception):
    pass


if not TYPE_CHECKING:
    _base_solve_dependencies = utils.solve_dependencies

    @wraps(_base_solve_dependencies)
    async def _solve_dependencies(
        *,
        request: Request | WebSocket,
        dependency_cache: DependencyCache | None = None,
        **kwargs: Any,
    ) -> utils.SolvedDependency:
        # a scope brought its own cache - it already reads through to the request one,
        # and knows what its overrides make unusable there
        if not isinstance(dependency_cache, ScopeCache):
            if (current_cache := request.scope.get(_DEPENDENCY_CACHE_KEY)) is not None:
                dependency_cache = current_cache
            elif dependency_cache is None:
                dependency_cache = {}

            request.scope[_DEPENDENCY_CACHE_KEY] = dependency_cache

        return await _base_solve_dependencies(
            request=request,
            dependency_cache=dependency_cache,
            **kwargs,
        )

    utils.solve_dependencies = _solve_dependencies
    routing.solve_dependencies = _solve_dependencies


def _get_dependency_cache(connection: HTTPConnection) -> DependencyCache:
    try:
        return connection.scope[_DEPENDENCY_CACHE_KEY]
    except KeyError:
        raise MissingDependencyCacheError("Dependency cache not found") from None


def _get_overrides_provider(connection: HTTPConnection) -> HasDependencyOverrides | None:
    route = connection.scope.get("route")

    if (provider := getattr(route, "dependency_overrides_provider", None)) is not None:
        return provider

    # a websocket route does not keep the provider it was given - but it is the app
    # the route was added to, which is what the scope of the connection holds
    return connection.scope.get("app")


# annotated as the base class so FastAPI hands over whichever the route has -
# a `Request` in an HTTP route, a `WebSocket` in a websocket one
async def init_inject_scope(connection: HTTPConnection) -> AsyncGenerator[None]:
    if not isinstance(connection, Request | WebSocket):  # pragma: no cover
        raise TypeError(f"expected a Request or a WebSocket, got {type(connection).__name__}")

    # the connection of the route: the middleware scope, if any, was bound before routing
    async with push_inject_scope(
        dependency_cache=_get_dependency_cache(connection),
        request=connection,
        provider=_get_overrides_provider(connection),
    ):
        yield


@dataclass
class InjectScopeMiddleware:
    app: ASGIApp

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        connection: BoundConnection

        match scope["type"]:
            case "http":
                connection = Request(scope, receive, send)
            case "websocket":
                connection = WebSocket(scope, receive, send)
            case _:
                await self.app(scope, receive, send)
                return

        scope[_DEPENDENCY_CACHE_KEY] = cache = {}

        async with push_inject_scope(
            dependency_cache=cache,
            request=connection,
            provider=scope.get("app"),
        ):
            await self.app(scope, receive, send)


def add_injected_scope(
    app: FastAPI,
    /,
) -> None:
    if not any(middleware.cls is InjectScopeMiddleware for middleware in app.user_middleware):
        app.add_middleware(InjectScopeMiddleware)

    if not any(dep.dependency is init_inject_scope for dep in app.router.dependencies):
        app.router.dependencies.insert(0, Depends(init_inject_scope))


__all__ = [
    "InjectScopeMiddleware",
    "MissingDependencyCacheError",
    "add_injected_scope",
    "init_inject_scope",
]
