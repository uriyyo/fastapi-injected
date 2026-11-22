from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, Security, params
from fastapi.security import HTTPBearer
from fastapi.testclient import TestClient
from starlette.middleware import Middleware
from starlette.middleware.gzip import GZipMiddleware
from starlette.requests import Request
from starlette.routing import Host, Mount, Route

from fastapi_injected import Dep, Injected, override_app
from fastapi_injected.ext import as_depends
from fastapi_injected.fastapi import add_lifespan
from fastapi_injected.walk import (
    iter_calls,
    iter_endpoints,
    iter_security,
)


async def endpoint() -> None:
    pass


def _build_app() -> FastAPI:
    inner = APIRouter()
    inner.get("/inner")(endpoint)

    outer = APIRouter()
    outer.get("/outer")(endpoint)
    outer.include_router(inner, prefix="/in")

    mounted = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    mounted.get("/mounted")(endpoint)

    hosted = APIRouter()
    hosted.get("/hosted")(endpoint)

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.include_router(outer, prefix="/r")
    app.router.routes.append(Mount("/m", mounted, middleware=[Middleware(GZipMiddleware)]))
    app.router.routes.append(Host("h.example", hosted))
    app.router.routes.append(Route("/plain", endpoint))

    return app


def test_iter_endpoints_reaches_included_mounted_and_hosted_routes():
    app = _build_app()

    @app.websocket("/ws")
    async def ws() -> None:
        pass

    found = [(path, route.path) for path, route in iter_endpoints(app)]

    # the plain starlette route is not an endpoint
    assert found == [
        ("/r/outer", "/outer"),
        ("/r/in/inner", "/inner"),
        ("/m/mounted", "/mounted"),
        ("/hosted", "/hosted"),
        ("/ws", "/ws"),
    ]


bearer = HTTPBearer()


def leaf() -> int:
    return 1


def middle(a: Annotated[int, Depends(leaf)], token: Annotated[str, Security(bearer, scopes=["read"])]) -> int:
    return a


async def root(b: Annotated[int, Depends(middle)], c: Annotated[int, Depends(leaf)]) -> int:
    return b + c


def test_iter_calls_is_unique_and_skips_root():
    assert [*iter_calls(root)] == [middle, leaf, bearer]
    assert [*iter_calls(Depends(middle))] == [leaf, bearer]
    assert [*iter_calls(leaf)] == []


def test_iter_calls_expands_composite_calls():
    class Composite:
        def __call__(self) -> None:
            pass

    composite = Composite()

    def func(c: Annotated[None, Depends(composite)]) -> None:
        pass

    calls = [*iter_calls(func, expand=lambda c: [leaf] if c is composite else [])]

    assert calls == [composite, leaf]


def test_iter_security_reports_schemes_with_scopes():
    assert [*iter_security(root)] == [(bearer, ["read"])]


def test_iter_calls_reads_injected_params():
    class Svc:
        pass

    async def func(item_id: int, svc: Dep[Svc] = Injected) -> None:
        pass

    assert [*iter_calls(func)] == [Svc]


def test_override_app_restores_previous_overrides():
    app = FastAPI()
    app.dependency_overrides[leaf] = lambda: 1

    with override_app(app, {leaf: lambda: 2, middle: lambda: 3}):
        assert {*app.dependency_overrides} == {leaf, middle}
        app.dependency_overrides[bearer] = lambda: 4

    assert {*app.dependency_overrides} == {leaf}
    assert app.dependency_overrides[leaf]() == 1


def test_as_depends_normalises_markers_hooks_and_callables():
    class Hooked:
        def __call__(self) -> None:
            pass

        def __get_depends__(self) -> params.Depends:
            return Depends(leaf, use_cache=False)

    marker = Security(bearer, scopes=["x"])

    assert as_depends(marker) is marker
    assert as_depends(leaf) == Depends(leaf)
    assert as_depends(Hooked()) == Depends(leaf, use_cache=False)


def test_add_lifespan_nests_inside_the_existing_one_and_merges_state():
    events: list[str] = []

    @asynccontextmanager
    async def outer(_: FastAPI) -> AsyncGenerator[dict[str, int]]:
        events.append("outer start")
        yield {"outer": 1}
        events.append("outer stop")

    @asynccontextmanager
    async def inner(_: FastAPI) -> AsyncGenerator[dict[str, int]]:
        events.append("inner start")
        yield {"inner": 2}
        events.append("inner stop")

    app = FastAPI(lifespan=outer)
    add_lifespan(app, inner)

    @app.get("/state")
    async def state(request: Request) -> dict[str, int]:
        return {**request.state._state}  # noqa: SLF001

    with TestClient(app) as client:
        assert client.get("/state").json() == {"outer": 1, "inner": 2}

    assert events == ["outer start", "inner start", "inner stop", "outer stop"]
