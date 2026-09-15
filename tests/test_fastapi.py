from typing import Annotated

import pytest
from fastapi import Depends, FastAPI, Header, Request, WebSocket, WebSocketDisconnect, status
from fastapi.testclient import TestClient
from starlette.requests import HTTPConnection
from starlette.websockets import WebSocketState

from fastapi_injected import Dep, Injected, init_inject_scope, inject, push_inject_scope, resolve
from fastapi_injected._fastapi_lifecycle import add_injected_scope
from fastapi_injected.scope import InjectScope

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
    scope = InjectScope.current()
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


@overridden_app.websocket("/ws")
async def overridden_ws_route(websocket: WebSocket, child: Dep[Child]) -> None:
    await websocket.accept()
    await websocket.send_json({"overridden": child is _overridden_child and await resolve(Child) is child})
    await websocket.close()


def test_app_dependency_overrides_are_used_in_websocket() -> None:
    overridden_app.dependency_overrides[Child] = _override_child

    try:
        with overridden_client.websocket_connect("/ws") as ws:
            assert ws.receive_json() == {"overridden": True}
    finally:
        overridden_app.dependency_overrides.clear()


async def _header_dep(x_trace: Annotated[str, Header()] = "missing") -> str:
    return x_trace


type Trace = Annotated[str, Depends(_header_dep)]


@inject(new_scope=True)
async def _in_new_scope(
    *,
    container: Dep[Container] = Injected,
    trace: Trace = Injected,
) -> tuple[Container, str]:
    return container, trace


@app.get("/new-scope")
async def new_scope_route(container: Dep[Container], trace: Trace) -> dict[str, bool]:
    fresh, fresh_trace = await _in_new_scope()

    return {
        # a new scope builds its dependencies again ...
        "is_fresh": fresh is not container,
        # ... without leaving the request they are built for
        "keeps_request": fresh_trace == trace,
    }


def test_new_scope_is_fresh_and_keeps_the_request() -> None:
    result = client.get("/new-scope", headers={"x-trace": "sent"})

    assert result.status_code == status.HTTP_200_OK
    assert result.json() == {"is_fresh": True, "keeps_request": True}


@inject
async def _ws_func(
    *,
    container: Dep[Container] = Injected,
) -> Container:
    return container


@app.websocket("/ws")
async def ws_route(websocket: WebSocket, container: Dep[Container]) -> None:
    await websocket.accept()

    same = await resolve(Container) is container and await _ws_func() is container

    await websocket.send_json({"same": same})
    await websocket.close()


def test_websocket_cache_is_working() -> None:
    with client.websocket_connect("/ws") as ws:
        assert ws.receive_json() == {"same": True}


@app.websocket("/ws/items/{item_id}")
async def ws_item_route(websocket: WebSocket, item_id: ItemID) -> None:
    await websocket.accept()
    await websocket.send_json({"item_id": await resolve(ItemID) == item_id, "value": item_id})
    await websocket.close()


def test_websocket_resolve_uses_route_path() -> None:
    with client.websocket_connect("/ws/items/42") as ws:
        assert ws.receive_json() == {"item_id": True, "value": 42}


async def _ws_dep(websocket: WebSocket) -> WebSocket:
    return websocket


async def _connection_dep(connection: HTTPConnection) -> HTTPConnection:
    return connection


type WS = Annotated[WebSocket, Depends(_ws_dep)]
type Connection = Annotated[HTTPConnection, Depends(_connection_dep)]


@app.websocket("/ws/send")
async def ws_send_route(websocket: WebSocket) -> None:
    await websocket.accept()

    scope = InjectScope.current()
    assert scope is not None
    assert scope.request is not websocket

    async with push_inject_scope(request=websocket) as nested:
        assert nested.request is not websocket
        assert not nested.synthetic

        resolved = await resolve(WS)
        connection = await resolve(Connection)

        assert isinstance(connection, WebSocket)
        assert resolved.scope["path"] == websocket.scope["path"]

        await resolved.send_json({"from": "dependency"})

    await websocket.send_json({"from": "route"})
    await websocket.close()


def test_websocket_dependency_shares_the_handshake() -> None:
    with client.websocket_connect("/ws/send") as ws:
        assert ws.receive_json() == {"from": "dependency"}
        assert ws.receive_json() == {"from": "route"}


@app.websocket("/ws/close")
async def ws_close_route(websocket: WebSocket) -> None:
    await websocket.accept()

    resolved = await resolve(WS)
    await resolved.close()

    # closing through the bound websocket closed the one the route holds too
    assert websocket.application_state is WebSocketState.DISCONNECTED


def test_websocket_close_through_dependency_is_seen_by_the_route() -> None:
    with client.websocket_connect("/ws/close") as ws, pytest.raises(WebSocketDisconnect):
        ws.receive_json()


@app.websocket("/ws/state")
async def ws_state_route(websocket: WebSocket) -> None:
    await websocket.accept()
    websocket.state.value = 42

    async with push_inject_scope(request=websocket) as scope:
        assert scope.request.state.value == 42
        scope.request.state.value = 43

    await websocket.send_json({"value": websocket.state.value})
    await websocket.close()


def test_websocket_nested_scope_shares_state() -> None:
    with client.websocket_connect("/ws/state") as ws:
        assert ws.receive_json() == {"value": 43}


_ws_states: list[ContextState] = []


@app.websocket("/ws/teardown")
async def ws_teardown_route(websocket: WebSocket) -> None:
    await websocket.accept()

    _ws_states.append(await resolve(ctx_dep))
    await websocket.send_json({"closed": _ws_states[-1].closed})
    await websocket.close()


def test_websocket_dependencies_are_torn_down_with_the_connection() -> None:
    _ws_states.clear()

    with client.websocket_connect("/ws/teardown") as ws:
        assert ws.receive_json() == {"closed": False}

    assert [state.closed for state in _ws_states] == [True]


@app.websocket("/ws/new-scope")
async def ws_new_scope_route(websocket: WebSocket, container: Dep[Container]) -> None:
    await websocket.accept()

    fresh, _ = await _in_new_scope()

    await websocket.send_json({"is_fresh": fresh is not container})
    await websocket.close()


def test_websocket_new_scope_is_fresh() -> None:
    with client.websocket_connect("/ws/new-scope") as ws:
        assert ws.receive_json() == {"is_fresh": True}
