import inspect
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Annotated, Any

import pytest
from fastapi import APIRouter, Depends, FastAPI, Header, Security, params
from fastapi.routing import APIRoute
from fastapi.security import HTTPBearer
from fastapi.testclient import TestClient
from starlette.middleware import Middleware
from starlette.middleware.gzip import GZipMiddleware
from starlette.requests import Request
from starlette.routing import Host, Mount, Route, Router

from fastapi_injected import (
    Arg,
    Dep,
    Injected,
    ParamRole,
    Signature,
    as_depends,
    override_app,
)
from fastapi_injected.reflect import (
    ParamKind,
    add_lifespan,
    add_route_dependency,
    as_dependant,
    find_dependant,
    find_route,
    iter_api_routes,
    iter_calls,
    iter_dependant,
    iter_operations,
    iter_overridden,
    iter_params,
    iter_routers,
    iter_routes,
    iter_routes_where,
    iter_security,
    match_route,
    operation_for,
    response_type,
)


async def endpoint() -> None:
    pass


def _build_app() -> tuple[FastAPI, list[tuple[str, Router]]]:
    inner = APIRouter()
    inner.get("/inner")(endpoint)

    outer = APIRouter()
    outer.get("/outer")(endpoint)
    outer.include_router(inner, prefix="/in")

    mounted = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    mounted.get("/mounted")(endpoint)

    hosted = Router([Route("/hosted", endpoint)])

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.include_router(outer, prefix="/r")
    app.router.routes.append(Mount("/m", mounted, middleware=[Middleware(GZipMiddleware)]))
    app.router.routes.append(Host("h.example", hosted))

    return app, [("", app.router), ("/r", outer), ("/r/in", inner), ("/m", mounted.router), ("", hosted)]


def test_iter_routes_reaches_included_mounted_and_hosted_routes():
    app, _ = _build_app()

    paths = [path for path, route in iter_routes(app) if isinstance(route, APIRoute | Route)]

    assert paths == ["/r/outer", "/r/in/inner", "/m/mounted", "/hosted"]


def test_iter_routers_yields_every_router_in_discovery_order():
    app, routers = _build_app()

    assert [*iter_routers(app)] == routers


def test_iter_api_routes_and_find_route():
    app, _ = _build_app()

    assert [path for path, _ in iter_api_routes(app)] == ["/r/outer", "/r/in/inner", "/m/mounted"]
    assert find_route(app, method="get", path="/r/in/inner").path == "/inner"
    assert find_route(app, name="endpoint").path == "/outer"

    with pytest.raises(LookupError):
        find_route(app, method="POST", path="/r/outer")


bearer = HTTPBearer()


def leaf() -> int:
    return 1


def middle(a: Annotated[int, Depends(leaf)], token: Annotated[str, Security(bearer, scopes=["read"])]) -> int:
    return a


async def root(b: Annotated[int, Depends(middle)], c: Annotated[int, Depends(leaf)]) -> int:
    return b + c


def test_iter_dependant_accepts_callables_and_depends():
    assert next(iter_dependant(Depends(middle))).call is middle
    assert len([*iter_dependant(root, mode="dfs")]) == 5


def test_iter_calls_is_unique_and_skips_root():
    assert [*iter_calls(root)] == [middle, leaf, bearer]
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


class Leaf:
    pass


def test_match_route_resolves_the_path_template():
    app, _ = _build_app()

    def scope(path: str, method: str = "GET", host: str = "x") -> dict[str, Any]:
        return {"type": "http", "method": method, "path": path, "headers": [(b"host", host.encode())]}

    def matched(path: str, **kwargs: str) -> str:
        found = match_route(app, scope(path, **kwargs))
        assert found is not None
        return found[0]

    assert match_route(app, scope("/r/in/inner")) == ("/r/in/inner", find_route(app, path="/r/in/inner"))
    assert matched("/m/mounted") == "/m/mounted"
    assert matched("/hosted", host="h.example") == "/hosted"
    assert match_route(app, scope("/nope")) is None
    # a method mismatch still names the route, like Starlette's own 405 handling
    assert matched("/r/outer", method="POST") == "/r/outer"
    assert match_route(app, Request(scope("/r/outer"))) is not None


def test_iter_params_reports_fields_with_their_owner():
    def dep(q: str) -> str:
        return q

    def endpoint(item_id: int, d: Annotated[str, Depends(dep)]) -> None:
        pass

    found = {(kind, field.name) for _, kind, field in iter_params(endpoint)}

    # a bare callable has no path, so item_id is read from the query like FastAPI would
    assert found == {(ParamKind.query, "item_id"), (ParamKind.query, "q")}
    assert all(isinstance(kind, ParamKind) for _, kind, _ in iter_params(endpoint))

    with_path = {(kind, field.name) for _, kind, field in iter_params(as_dependant(endpoint, path="/items/{item_id}"))}

    assert with_path == {(ParamKind.path, "item_id"), (ParamKind.query, "q")}


def test_as_dependant_rejects_a_dependant_built_for_another_path():
    app = FastAPI()

    @app.get("/items/{item_id}")
    async def item(item_id: int) -> None:
        pass

    route = find_route(app, path="/items/{item_id}")

    assert as_dependant(route.dependant, path="/items/{item_id}") is route.dependant

    with pytest.raises(ValueError, match="built for path"):
        as_dependant(route.dependant, path="/other")


def test_as_dependant_keeps_injected_params_and_the_signature():
    class Svc:
        pass

    async def func(item_id: int, svc: Dep[Svc] = Injected) -> None:
        pass

    dependant = as_dependant(func)

    assert [p.name for p in dependant.query_params] == ["item_id"]
    assert [d.call for d in dependant.dependencies] == [Svc]
    assert inspect.signature(func).parameters["svc"].default is Injected


def test_signature_add_appends_keyword_only_before_kwargs():
    def func(a: int, **kwargs: Any) -> None:
        pass

    extra = inspect.Parameter("request", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=Request)
    sign = Signature.of(func).add(extra, inspect.Parameter("a", inspect.Parameter.KEYWORD_ONLY))

    assert [(p.name, p.kind) for p in sign.parameters.values()] == [
        ("a", inspect.Parameter.POSITIONAL_OR_KEYWORD),
        ("request", inspect.Parameter.KEYWORD_ONLY),
        ("kwargs", inspect.Parameter.VAR_KEYWORD),
    ]


def test_response_type_strips_annotated_and_optional():
    router = APIRouter()

    @router.get("/a", response_model=Annotated[int, "meta"] | None)
    async def a() -> None:
        pass

    @router.get("/b")
    async def b() -> list[int] | None:
        pass

    @router.get("/c", response_model=None)
    async def c() -> int:
        return 1

    routes = [route for _, route in iter_api_routes(router) if isinstance(route, APIRoute)]

    assert [response_type(route) for route in routes] == [int, list[int], int]
    assert response_type(routes[1], strip=False) == list[int] | None


def test_add_route_dependency_rebuilds_the_route():
    seen: list[str] = []

    def guard(token: str) -> None:
        seen.append(token)

    app = FastAPI()

    @app.get("/x")
    async def x() -> int:
        return 1

    def other() -> None:
        seen.append("other")

    route = find_route(app, path="/x")
    assert isinstance(route, APIRoute)
    add_route_dependency(route, guard, Depends(other))

    assert {guard, other} <= {*iter_calls(route.dependant)}
    assert ParamKind.query in {kind for _, kind, _ in iter_params(route.dependant)}

    client = TestClient(app)
    assert client.get("/x").status_code == 422
    assert client.get("/x", params={"token": "t"}).json() == 1
    # the parameterless dependency also ran on the rejected request
    assert seen == ["other", "t", "other"]
    assert app.openapi()["paths"]["/x"]["get"]["parameters"][0]["name"] == "token"


def test_websocket_routes_are_found():
    app = FastAPI()

    @app.websocket("/ws")
    async def ws() -> None:
        pass

    assert [path for path, _ in iter_api_routes(app)] == ["/ws"]
    assert find_route(app, method="WEBSOCKET", path="/ws").name == "ws"
    assert [(m, p) for m, p, _ in iter_routes_where(app, lambda _: True)] == [("WEBSOCKET", "/ws")]


def test_iter_routes_where_reports_each_method():
    app, _ = _build_app()

    @app.api_route("/multi", methods=["GET", "POST"], dependencies=[Depends(leaf)])
    async def multi() -> None:
        pass

    found = [(m, p) for m, p, _ in iter_routes_where(app, lambda r: r.name == "multi")]

    assert found == [("GET", "/multi"), ("POST", "/multi")]
    # the authorization-test question: which routes do (not) reach a guard
    assert {p for _, p, _ in iter_routes_where(app, lambda r: leaf in iter_calls(r.dependant))} == {"/multi"}
    assert "/multi" not in {p for _, p, _ in iter_routes_where(app, lambda r: leaf not in iter_calls(r.dependant))}


def test_find_dependant_returns_the_chain_to_the_call():
    chain = find_dependant(root, leaf)

    assert [d.call for d in chain] == [root, middle, leaf]
    assert find_dependant(root, object()) == []


def test_iter_overridden_reports_calls_touched_by_an_override():
    assert iter_overridden(root, {leaf: lambda: 2}) == frozenset({root, middle, leaf})
    assert iter_overridden(root, [bearer]) == frozenset({root, middle, bearer})
    assert iter_overridden(root, {}) == frozenset()


def test_iter_operations_and_operation_for():
    app, _ = _build_app()

    assert [(m, p) for p, m, _ in iter_operations(app)] == [("GET", "/r/outer"), ("GET", "/r/in/inner")]
    assert operation_for(app, "get", "/r/outer")["operationId"] == "endpoint_r_outer_get"
    assert operation_for(app.openapi(), "GET", "/r/outer") is operation_for(app, "GET", "/r/outer")

    with pytest.raises(LookupError):
        operation_for(app, "POST", "/r/outer")


def test_override_app_restores_previous_overrides():
    app = FastAPI()
    app.dependency_overrides[leaf] = lambda: 1

    with override_app(app, {leaf: lambda: 2, middle: lambda: 3}):
        assert {*app.dependency_overrides} == {leaf, middle}
        app.dependency_overrides[bearer] = lambda: 4

    assert {*app.dependency_overrides} == {leaf}
    assert app.dependency_overrides[leaf]() == 1


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


def test_signature_drop_and_update():
    def func(a: int, request: Request, *, b: str = "x") -> None:
        pass

    sign = Signature.of(func)

    assert Signature.of(sign) == sign
    assert [*sign.drop("request", "missing").parameters] == ["a", "b"]

    replaced = sign.update("b", annotation=int, default=1)
    assert replaced.parameters["b"].annotation is int
    assert replaced.parameters["b"].default == 1

    with pytest.raises(LookupError):
        sign.update("missing", default=1)


def test_signature_add_dep_is_understood_by_fastapi():
    def current() -> str:
        return "me"

    async def handler(**kwargs: Any) -> dict[str, Any]:
        return kwargs

    # FastAPI would read a leftover **kwargs as a query parameter, so it goes before the extras are added
    Signature.of(handler).drop("kwargs").add_dep("user", current, annotation=str).apply(handler)

    app = FastAPI()
    app.get("/")(handler)

    assert TestClient(app).get("/").json() == {"user": "me"}
    assert operation_for(app, "GET", "/").get("parameters", []) == []


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
    assert next(iter_dependant(Hooked())).call is leaf


def test_signature_chains_operations_and_applies_them():
    def current() -> str:
        return "me"

    async def handler(**values: Any) -> dict[str, Any]:
        return values

    q = inspect.Parameter("q", inspect.Parameter.KEYWORD_ONLY, annotation=str | None, default=None)
    base = Signature.of(handler).drop("values")
    built = base.add_dep("user", current, annotation=str).add(q).update("q", default="none")

    # each step is a new builder, the earlier one is untouched
    assert [*base.parameters] == []
    assert [*built.parameters] == ["user", "q"]
    assert isinstance(built, inspect.Signature)
    assert built.apply(handler) is handler
    assert inspect.signature(handler) == built

    app = FastAPI()
    app.get("/")(handler)

    assert TestClient(app).get("/").json() == {"user": "me", "q": "none"}


def test_signature_roles_select_annotations_and_defaults():
    def func(
        plain: int,
        arg: Arg[str],
        dep: Dep[int],
        marked: Any = Depends(leaf),  # noqa: B008
        *,
        header: Annotated[str, Header()] = "x",
    ) -> None:
        pass

    sign = Signature.of(func)

    assert [Signature.role(param) for param in sign.parameters.values()] == [
        ParamRole.plain,
        ParamRole.arg,
        ParamRole.dep,
        ParamRole.dep,
        ParamRole.request,
    ]
    assert [param.name for param in sign.select(ParamRole.dep, ParamRole.request)] == ["dep", "marked", "header"]
    assert [*sign.annotations] == ["plain", "arg", "dep", "marked", "header"]
    assert sign.defaults == {"marked": sign.parameters["marked"].default, "header": "x"}


def test_signature_prepend_rename_returns_and_wrap():
    async def func(a: int, *, b: str = "x") -> int:
        return a

    extra = inspect.Parameter("z", inspect.Parameter.KEYWORD_ONLY, annotation=str)
    sign = Signature.of(func).prepend(extra).rename("a", "first").returns(str)

    assert [*sign.parameters] == ["z", "first", "b"]
    assert sign.parameters["z"].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
    assert sign.return_annotation is str
    assert Signature.of(func).prepend(inspect.Parameter("a", inspect.Parameter.KEYWORD_ONLY)) == Signature.of(func)

    wrapped = sign.wrap(func)

    assert wrapped is not func
    assert inspect.signature(wrapped) == sign
    assert inspect.iscoroutinefunction(wrapped)
    assert inspect.signature(func) != sign

    def sync_func() -> int:
        return 1

    assert Signature.of(sync_func).wrap(sync_func)() == 1
