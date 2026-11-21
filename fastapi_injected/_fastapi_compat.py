from typing import Any

from fastapi.dependencies.utils import (
    _get_body_field,
    _get_flat_body_params,
    _should_embed_body_fields,
    _solve_generator,
)
from fastapi.routing import APIRoute, APIRouter, APIWebSocketRoute, _build_dependant_with_parameterless_dependencies
from starlette.routing import Mount
from starlette.types import ASGIApp

INNER_ASTACK_KEY = "fastapi_inner_astack"
FUNCTION_ASTACK_KEY = "fastapi_function_astack"
MIDDLEWARE_ASTACK_KEY = "fastapi_middleware_astack"
ASYNC_CLEANUP_SCOPES_KEY = "fastapi_async_cleanup_scopes"

solve_generator = _solve_generator
flat_body_params = _get_flat_body_params
should_embed_body_fields = _should_embed_body_fields


def embed_body_fields(route: APIRoute | APIWebSocketRoute, /) -> bool:
    return route._embed_body_fields  # noqa: SLF001


def rebuild_dependant(route: APIRoute | APIWebSocketRoute, /) -> list[Any]:
    route.dependant, body_params, route._embed_body_fields = _build_dependant_with_parameterless_dependencies(  # noqa: SLF001
        path=route.path_format,
        call=route.endpoint,
        dependencies=route.dependencies,
    )
    return body_params


def rebuild_body_field(route: APIRoute, body_params: list[Any], /) -> None:
    route.body_field = _get_body_field(
        body_params=body_params,
        name=route.unique_id,
        embed_body_fields=route._embed_body_fields,  # noqa: SLF001
    )


def routes_version(router: APIRouter, /) -> int:
    return router._get_routes_version()  # noqa: SLF001


def mark_routes_changed(router: APIRouter, /) -> None:
    # an included router rebuilds its copy of the routes once this changes
    router._mark_routes_changed()  # noqa: SLF001


def mount_app(mount: Mount, /) -> ASGIApp:
    return mount._base_app  # noqa: SLF001


__all__ = [
    "ASYNC_CLEANUP_SCOPES_KEY",
    "FUNCTION_ASTACK_KEY",
    "INNER_ASTACK_KEY",
    "MIDDLEWARE_ASTACK_KEY",
    "embed_body_fields",
    "flat_body_params",
    "mark_routes_changed",
    "mount_app",
    "rebuild_body_field",
    "rebuild_dependant",
    "routes_version",
    "should_embed_body_fields",
    "solve_generator",
]
