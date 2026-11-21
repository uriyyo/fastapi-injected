from collections.abc import Collection, Iterable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, FastAPI, Header, Query, params
from fastapi.testclient import TestClient

from fastapi_injected import resolve
from fastapi_injected.ext import MakeDataclass
from fastapi_injected.openapi import (
    HasDocDepends,
    add_openapi,
    add_openapi_hook,
    invalidate_openapi,
    iter_doc_depends,
)
from fastapi_injected.reflect import find_route, operation_for


async def _tenant(x_tenant: Annotated[str, Header()]) -> str:
    return x_tenant


class LazyTenant(MakeDataclass):
    """Reads the tenant only inside its call - FastAPI never sees the header without `__doc_depends__`."""

    async def __call__(self) -> str:
        return await resolve(_tenant)

    def __doc_depends__(self, methods: Collection[str], /) -> Iterable[params.Depends]:
        return [Depends(_tenant)]


def _params(app: FastAPI, method: str, path: str) -> list[str]:
    return [param["name"] for param in operation_for(app, method, path).get("parameters", [])]


def test_lazy_dependency_is_a_doc_depends() -> None:
    assert isinstance(LazyTenant(), HasDocDepends)


def test_doc_depends_are_documented() -> None:
    app = FastAPI()

    @app.get("/plain")
    async def plain() -> None:
        pass

    @app.get("/lazy", dependencies=[Depends(LazyTenant())])
    async def lazy() -> None:
        pass

    assert _params(app, "GET", "/lazy") == []

    add_openapi(app)

    assert _params(app, "GET", "/lazy") == ["x-tenant"]
    assert _params(app, "GET", "/plain") == []


def test_doc_depends_deep_in_the_tree_and_under_a_prefix() -> None:
    async def service(tenant: Annotated[str, Depends(LazyTenant())]) -> str:
        return tenant  # pragma: no cover

    router = APIRouter()

    @router.get("/items")
    async def items(page: Annotated[int, Query()], svc: Annotated[str, Depends(service)]) -> None:
        pass

    app = FastAPI()
    app.include_router(router, prefix="/v1")
    add_openapi(app)

    assert _params(app, "GET", "/v1/items") == ["page", "x-tenant"]


def test_equal_doc_depends_are_documented_once() -> None:
    app = FastAPI()

    @app.get("/twice", dependencies=[Depends(LazyTenant()), Depends(LazyTenant())])
    async def twice() -> None:
        pass

    route = find_route(app, path="/twice")

    assert len([*iter_doc_depends(route)]) == 1


def test_hooks_run_in_order_once_and_are_cached() -> None:
    app = FastAPI()
    calls: list[str] = []

    def first(_: FastAPI, schema: dict[str, Any]) -> None:
        calls.append("first")
        schema["info"]["x-first"] = True

    def second(_: FastAPI, schema: dict[str, Any]) -> dict[str, Any]:
        calls.append("second")
        return {**schema, "x-second": schema["info"].get("x-first")}

    add_openapi_hook(app, first)
    add_openapi_hook(app, second)
    add_openapi_hook(app, first)

    schema = app.openapi()

    assert schema["x-second"] is True
    assert app.openapi() is schema
    assert calls == ["first", "second"]

    invalidate_openapi(app)
    app.openapi()

    assert calls == ["first", "second", "first", "second"]


def test_a_custom_openapi_is_kept() -> None:
    app = FastAPI()

    def custom() -> dict[str, Any]:
        return {"openapi": "3.1.0", "info": {"title": "custom", "version": "1"}, "paths": {}}

    app.openapi = custom  # type: ignore[method-assign]
    add_openapi_hook(app, lambda _, schema: {**schema, "x-hooked": True})

    assert app.openapi() == {**custom(), "x-hooked": True}


def test_docs_are_served_from_the_schema() -> None:
    app = FastAPI()
    add_openapi_hook(app, lambda _, schema: {**schema, "x-hooked": True})

    assert TestClient(app).get("/openapi.json").json()["x-hooked"] is True
