from collections.abc import Callable, Generator, Iterable
from typing import Any, Protocol, runtime_checkable

from fastapi import params
from fastapi.dependencies.models import Dependant
from fastapi.dependencies.utils import get_dependant
from fastapi.routing import APIRoute, APIWebSocketRoute, iter_route_contexts
from fastapi.security.base import SecurityBase
from starlette.applications import Starlette
from starlette.routing import BaseRoute, Router

from ._deps_tp import as_depends

type Endpoint = APIRoute | APIWebSocketRoute
type _DependantSource = Dependant | params.Depends | Callable[..., Any]


@runtime_checkable
class _HasRoutes(Protocol):
    routes: list[BaseRoute]


def _iter_routes(routes: list[BaseRoute], prefix: str = "", /) -> Generator[tuple[str, BaseRoute]]:
    for context in iter_route_contexts(routes):
        route = context.original_route
        path = prefix + (context.path or "")

        yield path, route

        match route:
            case _HasRoutes(routes=sub_routes):
                yield from _iter_routes(sub_routes, path)
            case _:
                pass


def iter_endpoints(root: Router | Starlette, /) -> Generator[tuple[str, Endpoint]]:
    for path, route in _iter_routes(root.routes):
        if isinstance(route, APIRoute | APIWebSocketRoute):
            yield path, route


def _as_dependant(node: _DependantSource, /) -> Dependant:
    if isinstance(node, Dependant):
        return node

    if (dependency := as_depends(node).dependency) is None:
        # a bare Depends() only means something next to the annotation it sits on
        raise TypeError("Depends() without a dependency has no dependant of its own")

    return get_dependant(path="", call=dependency)


def _walk(node: Dependant, /) -> Generator[Dependant]:
    yield node

    for sub in node.dependencies:
        yield from _walk(sub)


def iter_calls(
    root: _DependantSource,
    /,
    *,
    expand: Callable[[Any], Iterable[Any]] | None = None,
) -> Generator[Any]:
    seen: set[int] = set()

    def _expand(call: Any, /) -> Generator[Any]:
        if id(call) in seen:
            return

        seen.add(id(call))

        yield call

        if expand is None:
            return

        for sub_call in expand(call):
            yield from _expand(sub_call)

    it = _walk(_as_dependant(root))
    next(it, None)  # skip root

    for node in it:
        if node.call is not None:
            yield from _expand(node.call)


def iter_security(root: _DependantSource, /) -> Generator[tuple[SecurityBase, list[str]]]:
    seen: set[tuple[int, tuple[str, ...]]] = set()

    for node in _walk(_as_dependant(root)):
        if not isinstance(node.call, SecurityBase):
            continue

        scopes = [*(node.own_oauth_scopes or ())]
        key = (id(node.call), (*scopes,))

        if key not in seen:
            seen.add(key)
            yield node.call, scopes


__all__ = [
    "Endpoint",
    "iter_calls",
    "iter_endpoints",
    "iter_security",
]
