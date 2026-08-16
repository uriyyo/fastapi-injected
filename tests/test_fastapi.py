from typing import Annotated

from fastapi import Depends, FastAPI, Request, status
from fastapi.testclient import TestClient

from fastapi_injected import Dep, Injected, init_inject_scope, inject, push_inject_scope, resolve
from fastapi_injected._fastapi_lifecycle import add_injected_scope
from fastapi_injected.scope import current_inject_scope

from .deps import Child, Container, ContextState, ctx_dep

app = FastAPI(
    dependencies=[
        Depends(init_inject_scope),
    ],
)

client = TestClient(app)


@inject
async def _func(
    *,
    container: Dep[Container] = Injected,
) -> Container:
    return container


@app.get("/")
async def route(container: Dep[Container]) -> str:
    assert await resolve(Container) is container
    assert await _func() is container

    return ""


def test_cache_is_working() -> None:
    result = client.get("/")
    assert result.status_code == status.HTTP_200_OK


async def _item_id_dep(item_id: int) -> int:
    return item_id


type ItemID = Annotated[int, Depends(_item_id_dep)]


@app.get("/items/{item_id}")
async def item_route(item_id: ItemID) -> int:
    assert await resolve(ItemID) == item_id

    return item_id


def test_resolve_uses_route_path() -> None:
    result = client.get("/items/42")

    assert result.status_code == status.HTTP_200_OK
    assert result.json() == 42


_nested_states: list[ContextState] = []


@app.get("/nested-scope")
async def nested_scope_route(request: Request) -> dict[str, int]:
    async with push_inject_scope(request=request):
        _nested_states.append(await resolve(ctx_dep))

    return {"closed_inside": sum(state.closed for state in _nested_states)}


def test_nested_scope_owns_its_lifetime() -> None:
    _nested_states.clear()

    result = client.get("/nested-scope")

    assert result.status_code == status.HTTP_200_OK
    assert result.json() == {"closed_inside": 1}


@app.get("/synthetic")
async def synthetic_route(request: Request) -> dict[str, bool]:
    scope = current_inject_scope()
    assert scope is not None

    async with push_inject_scope(request=request) as nested:
        return {"scope": scope.synthetic, "nested": nested.synthetic}


def test_request_scope_is_not_synthetic() -> None:
    result = client.get("/synthetic")

    assert result.status_code == status.HTTP_200_OK
    assert result.json() == {"scope": False, "nested": False}


@app.get("/nested-scope-state")
async def nested_scope_state_route(request: Request) -> bool:
    request.state.value = 42

    async with push_inject_scope(request=request) as scope:
        assert scope.request.state.value == 42
        assert scope.request.url.path == request.url.path

        scope.request.state.value = 43

    return request.state.value == 43


def test_nested_scope_shares_request_state() -> None:
    result = client.get("/nested-scope-state")

    assert result.status_code == status.HTTP_200_OK
    assert result.json() is True


def test_add_injected_scope() -> None:
    other_app = FastAPI()
    assert not other_app.router.dependencies

    add_injected_scope(other_app)
    assert [dep.dependency for dep in other_app.router.dependencies] == [init_inject_scope]


def test_add_injected_scope_is_idempotent() -> None:
    other_app = FastAPI(dependencies=[Depends(_item_id_dep)])

    add_injected_scope(other_app)
    add_injected_scope(other_app)

    assert [dep.dependency for dep in other_app.router.dependencies] == [
        init_inject_scope,
        _item_id_dep,
    ]


overridden_app = FastAPI()
add_injected_scope(overridden_app)

overridden_client = TestClient(overridden_app)


@inject
async def _injected_child(
    *,
    child: Dep[Child] = Injected,
) -> Child:
    return child


@overridden_app.get("/")
async def overridden_route() -> str:
    container = await resolve(Container)

    assert container.child is _overridden_child
    assert await _injected_child() is _overridden_child

    return ""


_overridden_child = Child()


async def _override_child() -> Child:
    return _overridden_child


def test_app_dependency_overrides_are_used() -> None:
    overridden_app.dependency_overrides[Child] = _override_child

    try:
        result = overridden_client.get("/")
    finally:
        overridden_app.dependency_overrides.clear()

    assert result.status_code == status.HTTP_200_OK
