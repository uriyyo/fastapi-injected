from fastapi import Depends, FastAPI, status
from fastapi.testclient import TestClient

from fastapi_injected import Dep, Injected, init_inject_scope, inject, resolve
from fastapi_injected._fastapi_lifecycle import add_injected_scope

from .deps import Child, Container

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


@app.get("/items/{item_id}")
async def item_route(item_id: int) -> int:
    # the route path is known to `resolve`, so `item_id` is solved as a path param
    assert await resolve(_item_id_dep) == item_id

    return item_id


def test_resolve_uses_route_path() -> None:
    result = client.get("/items/42")

    assert result.status_code == status.HTTP_200_OK
    assert result.json() == 42


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
