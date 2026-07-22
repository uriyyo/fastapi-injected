from collections.abc import AsyncIterable
from functools import wraps
from typing import TYPE_CHECKING, Any

from fastapi import Request, WebSocket, routing
from fastapi.dependencies import utils

from .scope import push_inject_scope
from .types import DependencyCache

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


def _get_dependency_cache(request: Request) -> DependencyCache:
    try:
        return request.scope[_DEPENDENCY_CACHE_KEY]
    except KeyError:
        raise MissingDependencyCacheError("Dependency cache not found") from None


async def init_inject_scope(request: Request) -> AsyncIterable[None]:
    async with push_inject_scope(
        dependency_cache=_get_dependency_cache(request),
        request=request,
    ):
        yield


__all__ = [
    "init_inject_scope",
]
