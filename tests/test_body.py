from typing import Annotated

import pytest
from fastapi import (
    Body,
    Cookie,
    Depends,
    FastAPI,
    File,
    Form,
    Header,
    Path,
    Query,
    Request,
    UploadFile,
    WebSocket,
    status,
)
from fastapi.testclient import TestClient
from pydantic import BaseModel
from starlette.datastructures import FormData
from starlette.types import Message

from fastapi_injected import (
    DependencyResolutionError,
    Injected,
    init_inject_scope,
    inject,
    push_inject_scope,
    resolve,
    synthetic_request,
)


class Item(BaseModel):
    name: str


async def _item(item: Item) -> Item:
    return item


async def _embedded_name(name: Annotated[str, Body(embed=True)]) -> str:
    return name


async def _form_name(name: Annotated[str, Form()]) -> str:
    return name


async def _upload(file: Annotated[UploadFile, File()]) -> bytes:
    return await file.read()


async def _raw(request: Request) -> bytes:
    return await request.body()


async def _trace(x_trace: Annotated[str, Header()]) -> str:
    return x_trace


async def _session(sid: Annotated[str, Cookie()]) -> str:
    return sid


async def _page(page: Annotated[int, Query()]) -> int:
    return page


async def _item_id(item_id: Annotated[int, Path()]) -> int:
    return item_id


type ItemDep = Annotated[Item, Depends(_item)]
type EmbeddedName = Annotated[str, Depends(_embedded_name)]
type FormName = Annotated[str, Depends(_form_name)]
type Upload = Annotated[bytes, Depends(_upload)]
type Trace = Annotated[str, Depends(_trace)]
type Session = Annotated[str, Depends(_session)]
type Page = Annotated[int, Depends(_page)]
type ItemID = Annotated[int, Depends(_item_id)]

app = FastAPI(dependencies=[Depends(init_inject_scope)])
client = TestClient(app)


@app.post("/route-body")
async def route_body(item: Item) -> dict[str, str]:
    resolved = await resolve(ItemDep)

    return {"route": item.name, "resolved": resolved.name}


@app.post("/no-route-body")
async def no_route_body(request: Request) -> dict[str, str]:
    resolved = await resolve(ItemDep)

    # what a dependency read is still there for the route
    return {"resolved": resolved.name, "raw": (await request.json())["name"]}


@app.post("/embedded")
async def embedded() -> str:
    return await resolve(EmbeddedName)


@app.post("/route-embeds")
async def route_embeds(item: Item, extra: Annotated[int, Body()]) -> dict[str, str | int]:
    # the route decides the shape of the body, and a dependency reads it as such
    resolved = await resolve(ItemDep)

    return {"resolved": resolved.name, "extra": extra}


@app.post("/form")
async def form() -> str:
    return await resolve(FormName)


@app.post("/upload")
async def upload() -> str:
    return (await resolve(Upload)).decode()


@app.post("/nested")
async def nested() -> list[str]:
    @inject(new_scope=True)
    async def _fresh(*, item: ItemDep = Injected) -> str:
        return item.name

    first = await _fresh()

    async with push_inject_scope():
        second = (await resolve(ItemDep)).name

    return [first, second]


@app.post("/invalid-json")
async def invalid_json() -> list[str]:
    try:
        await resolve(ItemDep)
    except DependencyResolutionError as exc:
        return [error["type"] for error in exc.errors]

    return []


@app.post("/raw")
async def raw_body() -> str:
    @inject
    async def _func(*, raw: Annotated[bytes, Depends(_raw)] = Injected) -> bytes:
        return raw

    return (await _func()).decode()


@app.post("/params/{item_id}")  # noqa: FAST003 - read by a resolved dependency
async def params() -> list[str | int]:
    return [await resolve(Trace), await resolve(Session), await resolve(Page), await resolve(ItemID)]


def test_body_the_route_read_is_resolved() -> None:
    result = client.post("/route-body", json={"name": "a"})

    assert result.status_code == status.HTTP_200_OK
    assert result.json() == {"route": "a", "resolved": "a"}


def test_body_is_read_when_the_route_has_none() -> None:
    result = client.post("/no-route-body", json={"name": "b"})

    assert result.status_code == status.HTTP_200_OK
    assert result.json() == {"resolved": "b", "raw": "b"}


def test_embedded_body_field() -> None:
    assert client.post("/embedded", json={"name": "c"}).json() == "c"


def test_body_keeps_the_shape_the_route_gave_it() -> None:
    result = client.post("/route-embeds", json={"item": {"name": "d"}, "extra": 1})

    assert result.status_code == status.HTTP_200_OK
    assert result.json() == {"resolved": "d", "extra": 1}


def test_form_body() -> None:
    assert client.post("/form", data={"name": "e"}).json() == "e"


def test_uploaded_file() -> None:
    assert client.post("/upload", files={"file": ("f.txt", b"content")}).json() == "content"


def test_nested_scopes_share_the_body() -> None:
    assert client.post("/nested", json={"name": "f"}).json() == ["f", "f"]


def test_invalid_json_body() -> None:
    result = client.post("/invalid-json", content=b"{", headers={"content-type": "application/json"})

    assert result.json() == ["json_invalid"]


def test_raw_body_is_left_to_the_dependency() -> None:
    assert client.post("/raw", content=b"raw").json() == "raw"


def test_request_parameters_are_resolved() -> None:
    result = client.post(
        "/params/7?page=3",
        headers={"x-trace": "t"},
        cookies={"sid": "s"},
    )

    assert result.json() == ["t", "s", 3, 7]


@pytest.mark.asyncio
async def test_synthetic_request_carries_request_parameters():
    request = synthetic_request(
        headers={"X-Trace": "t"},
        cookies={"sid": "s"},
        query={"page": "3"},
        path_params={"item_id": 7},
    )

    async with push_inject_scope(request=request) as scope:
        assert scope.synthetic
        assert [await resolve(Trace), await resolve(Session), await resolve(Page), await resolve(ItemID)] == [
            "t",
            "s",
            3,
            7,
        ]


@pytest.mark.asyncio
async def test_synthetic_request_json_body():
    async with push_inject_scope(request=synthetic_request(body={"name": "g"})):
        assert await resolve(ItemDep) == Item(name="g")
        assert await resolve(ItemDep, new_scope=True) == Item(name="g")


@pytest.mark.asyncio
async def test_synthetic_request_model_body():
    async with push_inject_scope(request=synthetic_request(body=Item(name="h"))):
        assert await resolve(ItemDep) == Item(name="h")


@pytest.mark.asyncio
async def test_synthetic_request_raw_body():
    async with push_inject_scope(request=synthetic_request(body=b"raw")):
        assert await resolve(_raw) == b"raw"

    async with push_inject_scope(request=synthetic_request(body="text")):
        assert await resolve(_raw) == b"text"


@pytest.mark.asyncio
async def test_synthetic_request_form_body():
    request = synthetic_request(
        body="name=i",
        headers={"content-type": "application/x-www-form-urlencoded"},
    )

    async with push_inject_scope(request=request):
        assert await resolve(FormName) == "i"


@pytest.mark.asyncio
async def test_synthetic_request_keeps_its_app():
    app = FastAPI()

    async with push_inject_scope(request=synthetic_request(app=app)) as scope:
        assert scope.bound_request.app is app


@pytest.mark.asyncio
async def test_missing_body_is_reported():
    with pytest.raises(DependencyResolutionError) as exc_info:
        await resolve(ItemDep)

    [error] = exc_info.value.errors

    assert error["type"] == "missing"
    assert error["loc"] == ("body",)


@pytest.mark.asyncio
async def test_body_is_read_once():
    reads = 0
    request = synthetic_request(body={"name": "j"})
    receive = request.receive

    async def _counting_receive() -> Message:
        nonlocal reads
        reads += 1
        return await receive()

    request._receive = _counting_receive  # noqa: SLF001

    async with push_inject_scope(request=request):
        assert await resolve(ItemDep) == Item(name="j")
        assert await resolve(EmbeddedName, new_scope=True) == "j"

    assert reads == 1


async def _streamed(request: Request) -> bytes:
    return b"".join([chunk async for chunk in request.stream()])


@pytest.mark.asyncio
async def test_rebound_request_streams_and_closes_through_the_original():
    request = synthetic_request(body=b"streamed")

    async with push_inject_scope(request=request) as scope:
        assert await resolve(_streamed) == b"streamed"

        await scope.bound_request.close()


@pytest.mark.parametrize(
    ("body", "headers", "expected"),
    [
        (b'{"name": "k"}', {}, b'{"name": "k"}'),
        (b'{"name": "k"}', {"content-type": "text/plain"}, b'{"name": "k"}'),
        (b'{"name": "k"}', {"content-type": "application/xml"}, b'{"name": "k"}'),
        (b"", {"content-type": "application/json"}, None),
    ],
    ids=["no-content-type", "not-application", "not-json", "empty"],
)
@pytest.mark.asyncio
async def test_body_that_is_not_json_is_kept_raw(body: bytes, headers: dict[str, str], expected: bytes | None):
    async def _received(item: Annotated[bytes | None, Body()] = None) -> bytes | None:
        return item

    async with push_inject_scope(request=synthetic_request(body=body, headers=headers)):
        assert await resolve(_received) == expected


@pytest.mark.asyncio
async def test_form_is_closed_once_per_request(monkeypatch: pytest.MonkeyPatch):
    closed = 0
    close = FormData.close

    async def _counting_close(self: FormData) -> None:
        nonlocal closed
        closed += 1
        await close(self)

    monkeypatch.setattr(FormData, "close", _counting_close)

    request = synthetic_request(body="name=l", headers={"content-type": "application/x-www-form-urlencoded"})

    async with push_inject_scope(request=request):
        assert await resolve(FormName) == "l"

        async with push_inject_scope():
            assert await resolve(FormName, new_scope=True) == "l"

    assert closed == 1


@app.post("/route-form")
async def route_form(name: Annotated[str, Form()]) -> list[str]:
    # the route parsed the form, a dependency reads the same one
    return [name, await resolve(FormName)]


@app.post("/route-upload")
async def route_upload(file: Annotated[UploadFile, File()]) -> list[str]:
    return [file.filename or "", (await resolve(Upload)).decode()]


@app.post("/route-body-nested")
async def route_body_nested(item: Item) -> list[str]:
    async with push_inject_scope():
        nested = (await resolve(ItemDep)).name

    return [item.name, nested, (await resolve(ItemDep, new_scope=True)).name]


@app.post("/route-body-invalid")
async def route_body_invalid(item: Annotated[bytes, Body()]) -> list[str]:
    # the route took the body as it came, so a dependency asking for a model gets the same bytes
    try:
        await resolve(ItemDep)
    except DependencyResolutionError as exc:
        return [item.decode(), *(error["type"] for error in exc.errors)]

    return []  # pragma: no cover


@app.post("/route-body-empty")
async def route_body_empty(item: Item | None = None) -> list[str]:
    try:
        await resolve(ItemDep)
    except DependencyResolutionError as exc:
        return [str(item), *(f"{error['type']}@{'.'.join(map(str, error['loc']))}" for error in exc.errors)]

    return []  # pragma: no cover


@app.post("/untouched")
async def untouched(request: Request) -> str:
    # nothing resolved asks for the body, so the route is the first to read it
    await resolve(Trace)

    return (await request.body()).decode()


@app.websocket("/ws")
async def ws(websocket: WebSocket) -> None:
    await websocket.accept()

    try:
        await resolve(ItemDep)
    except DependencyResolutionError as exc:
        await websocket.send_json([error["type"] for error in exc.errors])

    await websocket.close()


def test_form_the_route_read_is_resolved(monkeypatch: pytest.MonkeyPatch) -> None:
    closed = 0
    close = FormData.close

    async def _counting_close(self: FormData) -> None:
        nonlocal closed
        closed += 1
        await close(self)

    monkeypatch.setattr(FormData, "close", _counting_close)

    assert client.post("/route-form", data={"name": "m"}).json() == ["m", "m"]
    assert closed == 1


def test_upload_the_route_read_is_resolved() -> None:
    assert client.post("/route-upload", files={"file": ("n.txt", b"n")}).json() == ["n.txt", "n"]


def test_nested_scopes_in_a_route_share_its_body() -> None:
    assert client.post("/route-body-nested", json={"name": "o"}).json() == ["o", "o", "o"]


def test_body_the_route_took_raw_stays_raw() -> None:
    result = client.post("/route-body-invalid", content=b"p", headers={"content-type": "text/plain"})

    assert result.json() == ["p", "model_attributes_type"]


def test_empty_body_on_a_route_declaring_one() -> None:
    result = client.post("/route-body-empty")

    assert result.status_code == status.HTTP_200_OK
    assert result.json() == ["None", "missing@body"]


def test_body_is_left_untouched_when_nothing_asks_for_it() -> None:
    assert client.post("/untouched", content=b"q", headers={"x-trace": "t"}).json() == "q"


def test_websocket_has_no_body() -> None:
    with client.websocket_connect("/ws") as connection:
        assert connection.receive_json() == ["missing"]


@pytest.mark.asyncio
async def test_synthetic_request_closes_the_form_with_its_outermost_scope(monkeypatch: pytest.MonkeyPatch):
    closed = 0
    close = FormData.close

    async def _counting_close(self: FormData) -> None:
        nonlocal closed
        closed += 1
        await close(self)

    monkeypatch.setattr(FormData, "close", _counting_close)

    request = synthetic_request(body="name=r", headers={"content-type": "application/x-www-form-urlencoded"})

    async with push_inject_scope(request=request):
        async with push_inject_scope():
            assert await resolve(FormName) == "r"

        # a nested scope read it first, it is still there for the one it is nested in
        assert closed == 0
        assert await resolve(FormName) == "r"

    assert closed == 1


async def _api_key(key: Annotated[str, Header(alias="X-Api-Key")]) -> str:
    return key


@app.get("/api-key")
async def api_key() -> str:
    return await resolve(_api_key)


def test_header_with_an_alias() -> None:
    assert client.get("/api-key", headers={"x-api-key": "secret"}).json() == "secret"


@pytest.mark.asyncio
async def test_header_with_an_alias_on_a_synthetic_request():
    async with push_inject_scope(request=synthetic_request(headers={"x-api-key": "secret"})):
        assert await resolve(_api_key) == "secret"

    async with push_inject_scope(request=synthetic_request()):
        with pytest.raises(DependencyResolutionError) as exc_info:
            await resolve(_api_key)

    [error] = exc_info.value.errors

    assert (error["type"], error["loc"]) == ("missing", ("header", "X-Api-Key"))
