from collections.abc import Callable, Collection, Iterable, Iterator
from dataclasses import dataclass, field
from typing import Any, Protocol, cast, runtime_checkable

from fastapi import APIRouter, FastAPI, params
from fastapi.openapi.utils import get_openapi
from fastapi.routing import APIRoute, iter_route_contexts
from starlette.routing import BaseRoute

from .reflect import iter_calls


@runtime_checkable
class HasDocDepends(Protocol):
    def __doc_depends__(self, methods: Collection[str], /) -> Iterable[params.Depends]: ...


type OpenAPIHook = Callable[[FastAPI, dict[str, Any]], dict[str, Any] | None]


def iter_doc_depends(route: Any, /) -> Iterator[params.Depends]:
    if (dependant := getattr(route, "dependant", None)) is None:
        return

    methods = getattr(route, "methods", None) or ()
    seen: list[params.Depends] = []

    for call in iter_calls(dependant):
        if isinstance(call, HasDocDepends):
            for dep in call.__doc_depends__(methods):
                if dep not in seen:
                    seen.append(dep)
                    yield dep


def _documented_routes(app: FastAPI, /) -> list[BaseRoute]:
    # contexts are built anew on every iteration, so they are collected once
    contexts = [(context, [*iter_doc_depends(context)]) for context in iter_route_contexts(app.routes)]

    if not any(extra for _, extra in contexts):
        return app.routes

    documented = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)

    for context, extra in contexts:
        original = context.original_route

        if isinstance(original, APIRoute):
            path = context.path or original.path
            prefix = path[: -len(original.path)] if path.endswith(original.path) else ""

            documented.include_router(APIRouter(routes=[original]), prefix=prefix, dependencies=extra)

    return documented.routes


def _build_openapi(app: FastAPI, /) -> dict[str, Any]:
    return get_openapi(
        title=app.title,
        version=app.version,
        openapi_version=app.openapi_version,
        summary=app.summary,
        description=app.description,
        terms_of_service=app.terms_of_service,
        contact=app.contact,
        license_info=app.license_info,
        routes=_documented_routes(app),
        webhooks=app.webhooks.routes,
        tags=app.openapi_tags,
        servers=app.servers,
        separate_input_output_schemas=app.separate_input_output_schemas,
        external_docs=app.openapi_external_docs,
    )


@dataclass
class _OpenAPI:
    app: FastAPI
    custom: Callable[[], dict[str, Any]] | None = None
    hooks: list[OpenAPIHook] = field(default_factory=list)

    def __call__(self) -> dict[str, Any]:
        if self.app.openapi_schema is None:
            schema = self.custom() if self.custom is not None else _build_openapi(self.app)

            for hook in self.hooks:
                if (changed := hook(self.app, schema)) is not None:
                    schema = changed

            self.app.openapi_schema = schema

        return self.app.openapi_schema


def add_openapi(app: FastAPI, /) -> None:
    if isinstance(app.openapi, _OpenAPI):
        return

    is_default = getattr(app.openapi, "__func__", None) is FastAPI.openapi

    app.openapi = _OpenAPI(app, custom=None if is_default else app.openapi)
    app.openapi_schema = None


def add_openapi_hook(app: FastAPI, hook: OpenAPIHook, /) -> None:
    add_openapi(app)
    hooks = cast("_OpenAPI", app.openapi).hooks

    if hook not in hooks:
        hooks.append(hook)
        invalidate_openapi(app)


def invalidate_openapi(app: FastAPI, /) -> None:
    app.openapi_schema = None


__all__ = [
    "HasDocDepends",
    "OpenAPIHook",
    "add_openapi",
    "add_openapi_hook",
    "invalidate_openapi",
    "iter_doc_depends",
]
