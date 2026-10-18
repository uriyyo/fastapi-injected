from collections.abc import AsyncGenerator, Callable, Generator, Mapping
from contextlib import asynccontextmanager
from typing import Any, Protocol, cast, runtime_checkable

from fastapi import params
from fastapi.dependencies.utils import (
    _get_body_field,
    get_typed_return_annotation,
)
from fastapi.routing import (
    APIRoute,
    APIWebSocketRoute,
    _build_dependant_with_parameterless_dependencies,
    iter_route_contexts,
    request_response,
)
from starlette.applications import Starlette
from starlette.requests import HTTPConnection
from starlette.routing import BaseRoute, Host, Match, Mount, Router
from starlette.types import Lifespan, Scope

from fastapi_injected._deps_tp import DependsSource, strip_annotation


def response_type(route: APIRoute, /, *, strip: bool = True) -> Any:
    tp = route.response_model

    if tp is None:
        tp = get_typed_return_annotation(route.endpoint)

    return strip_annotation(tp) if strip else tp


def _to_dep(_arg: Any) -> params.Depends:
    match _arg:
        case params.Depends():
            return _arg
        case _:
            return params.Depends(_arg)


def add_route_dependency(route: APIRoute, /, *deps: DependsSource) -> None:
    route.dependencies.extend(_to_dep(dep) for dep in deps)

    route.dependant, body_params, route._embed_body_fields = _build_dependant_with_parameterless_dependencies(  # noqa: SLF001
        path=route.path_format,
        call=route.endpoint,
        dependencies=route.dependencies,
    )
    route.body_field = _get_body_field(
        body_params=body_params,
        name=route.unique_id,
        embed_body_fields=route._embed_body_fields,  # noqa: SLF001
    )
    route.app = request_response(route.get_route_handler())


@runtime_checkable
class HasPrefix(Protocol):
    prefix: str


@runtime_checkable
class HasOriginalRouter(Protocol):
    original_router: Router
    include_context: HasPrefix


@runtime_checkable
class HasRouter(Protocol):
    router: Router


@runtime_checkable
class HasRoutes(Protocol):
    routes: list[BaseRoute]


@runtime_checkable
class HasPath(Protocol):
    path: str


def _sub_routes(route: BaseRoute, /) -> list[BaseRoute]:
    match route:
        case HasRoutes(routes=routes):
            return routes
        case _:
            return []


def _path(route: BaseRoute, /) -> str:
    match route:
        case HasOriginalRouter(
            include_context=HasPrefix(prefix=prefix),
        ):
            return prefix
        case HasPath(path=path):
            return path
        case _:
            return ""


def _iter_routes(routes: list[BaseRoute], prefix: str = "", /) -> Generator[tuple[str, BaseRoute]]:
    for context in iter_route_contexts(routes):
        route = context.original_route
        path = prefix + (context.path or "")

        yield path, route
        yield from _iter_routes(_sub_routes(route), path)


def iter_routes(root: Router | Starlette, /) -> Generator[tuple[str, BaseRoute]]:
    yield from _iter_routes(root.routes)


type Endpoint = APIRoute | APIWebSocketRoute


def iter_api_routes(root: Router | Starlette, /) -> Generator[tuple[str, Endpoint]]:
    for path, route in iter_routes(root):
        if isinstance(route, APIRoute | APIWebSocketRoute):
            yield path, route


def _methods(route: Endpoint, /) -> set[str]:
    return route.methods or set() if isinstance(route, APIRoute) else {"WEBSOCKET"}


def iter_routes_where(
    root: Router | Starlette,
    pred: Callable[[Endpoint], bool],
    /,
) -> Generator[tuple[str, str, Endpoint]]:
    for path, route in iter_api_routes(root):
        if pred(route):
            for method in sorted(_methods(route)):
                yield method, path, route


def find_route(
    root: Router | Starlette,
    /,
    *,
    method: str | None = None,
    path: str | None = None,
    name: str | None = None,
) -> Endpoint:
    for route_path, route in iter_api_routes(root):
        if method is not None and method.upper() not in _methods(route):
            continue

        if path is not None and route_path != path:
            continue

        if name is not None and route.name != name:
            continue

        return route

    raise LookupError(f"no route matches method={method!r} path={path!r} name={name!r}")


def _match_routes(routes: list[BaseRoute], scope: Scope, prefix: str, /) -> tuple[str, BaseRoute] | None:
    partial: tuple[str, BaseRoute] | None = None

    for context in iter_route_contexts(routes):
        match, child_scope = context.matches(scope)

        if match is Match.NONE:
            continue

        route = context.original_route
        path = prefix + (context.path or "")

        match route, match:
            case Mount() | Host(), Match.FULL:
                if found := _match_routes(route.routes, {**scope, **child_scope}, path):
                    return found
            case Mount() | Host(), _:
                pass
            case _, Match.FULL:
                return path, route
            case _ if partial is None:
                partial = path, route

    return partial


def match_route(
    root: Router | Starlette,
    connection: HTTPConnection | Scope,
    /,
) -> tuple[str, BaseRoute] | None:
    match connection:
        case HTTPConnection():
            scope = connection.scope
        case _:
            scope = {**connection}

    return _match_routes(root.routes, scope, "")


def _as_router(app: Any, /) -> Router | None:
    match app:
        case Router():
            return app
        case HasRouter(router=router):
            return router
        case _:
            return None


def _iter_routers(router: Router, prefix: str = "", /) -> Generator[tuple[str, Router]]:
    yield prefix, router

    for route in router.routes:
        match route:
            case HasOriginalRouter(original_router=original_router):
                sub = original_router
            case Mount():
                # .app is the middleware stack when the mount has middleware, _base_app is the app itself
                sub = route._base_app  # noqa: SLF001
            case Host(app=app):
                sub = app
            case _:
                continue

        if (sub_router := _as_router(sub)) is not None:
            yield from _iter_routers(sub_router, prefix + _path(route))


def iter_routers(root: Router | Starlette, /) -> Generator[tuple[str, Router]]:
    if (router := _as_router(root)) is not None:
        yield from _iter_routers(router)


def add_lifespan(root: Router | Starlette, lifespan: Lifespan[Any], /) -> None:
    router = _as_router(root)

    if router is None:
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
    "Endpoint",
    "add_lifespan",
    "add_route_dependency",
    "find_route",
    "iter_api_routes",
    "iter_routers",
    "iter_routes",
    "iter_routes_where",
    "match_route",
    "response_type",
]
