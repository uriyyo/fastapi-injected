from collections.abc import Callable
from typing import Any

from fastapi.dependencies import models
from fastapi.dependencies.utils import (
    _get_flat_body_params,
    _should_embed_body_fields,
    _solve_generator,
)
from fastapi.routing import APIRoute, APIRouter, APIWebSocketRoute

INNER_ASTACK_KEY = "fastapi_inner_astack"
FUNCTION_ASTACK_KEY = "fastapi_function_astack"
MIDDLEWARE_ASTACK_KEY = "fastapi_middleware_astack"
ASYNC_CLEANUP_SCOPES_KEY = "fastapi_async_cleanup_scopes"

_PATCHED_MARKER = "__fastapi_injected_patched__"

solve_generator = _solve_generator
flat_body_params = _get_flat_body_params
should_embed_body_fields = _should_embed_body_fields


def embed_body_fields(route: APIRoute | APIWebSocketRoute, /) -> bool:
    return route._embed_body_fields  # noqa: SLF001


def routes_version(router: APIRouter, /) -> int:
    return router._get_routes_version()  # noqa: SLF001


def patch_fastapi(target: object, name: str, wrap: Callable[[Any], Any], /) -> None:
    if getattr(current := getattr(target, name), _PATCHED_MARKER, False):
        return

    patched = wrap(current)
    setattr(patched, _PATCHED_MARKER, True)
    setattr(target, name, patched)


def patch_call_classifiers(wrap: Callable[[Any], Any], /) -> None:
    # the lru caches FastAPI keeps every call it classifies in, looked up by name on each use
    for name in (
        "_is_gen_callable_cached",
        "_is_async_gen_callable_cached",
        "_is_coroutine_callable_cached",
    ):
        patch_fastapi(models, name, wrap)


__all__ = [
    "ASYNC_CLEANUP_SCOPES_KEY",
    "FUNCTION_ASTACK_KEY",
    "INNER_ASTACK_KEY",
    "MIDDLEWARE_ASTACK_KEY",
    "embed_body_fields",
    "flat_body_params",
    "patch_call_classifiers",
    "patch_fastapi",
    "routes_version",
    "should_embed_body_fields",
    "solve_generator",
]
