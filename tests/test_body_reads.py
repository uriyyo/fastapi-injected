import asyncio
from typing import Annotated, Any

import pytest
from fastapi import Body, Depends, FastAPI, Form, Header, Request, status
from fastapi.testclient import TestClient
from pydantic import BaseModel
from starlette.types import ASGIApp, Message, Receive, Scope, Send

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


class Login(BaseModel):
    user: str
    password: str


async def _item(item: Item) -> Item:
    return item


async def _name(name: Annotated[str, Body(embed=True)]) -> str:
    return name


async def _pair(name: Annotated[str, Body()], extra: Annotated[int, Body()]) -> str:
    # two body fields of one dependency are embedded under their names, as in a route
    return f"{name}:{extra}"


async def _login(login: Annotated[Login, Form()]) -> str:
    return f"{login.user}/{login.password}"


async def _fields(user: Annotated[str, Form()], password: Annotated[str, Form()]) -> str:
    return f"{user}+{password}"


async def _trace(x_trace: Annotated[str, Header()]) -> str:
    return x_trace


type ItemDep = Annotated[Item, Depends(_item)]
type Name = Annotated[str, Depends(_name)]
type Pair = Annotated[str, Depends(_pair)]
type LoginDep = Annotated[str, Depends(_login)]
type Fields = Annotated[str, Depends(_fields)]
type Trace = Annotated[str, Depends(_trace)]


class _CountingReceive:
    # how many times the body was pulled from the connection - the one thing a cache must keep low
    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self.reads: list[int] = []

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":  # pragma: no cover
            await self.app(scope, receive, send)
            return

        reads = 0

        async def _receive() -> Message:
            nonlocal reads
            message = await receive()
            reads += message["type"] == "http.request"
            return message

        await self.app(scope, _receive, send)
        self.reads.append(reads)


app = FastAPI(dependencies=[Depends(init_inject_scope)])
counting = _CountingReceive(app)
client = TestClient(counting)


@pytest.fixture(autouse=True)
def _reset_reads() -> None:
    counting.reads.clear()


@app.post("/shapes")
async def shapes(request: Request) -> list[Any]:
    # one body, read once, handed to every dependency in the shape it asks for
    return [
        (await resolve(ItemDep)).name,
        await resolve(Name),
        await resolve(Name, new_scope=True),
        (await request.json())["name"],
    ]


@app.post("/pair")
async def pair() -> str:
    return await resolve(Pair)


@app.post("/concurrent")
async def concurrent() -> list[str]:
    @inject
    async def _one(*, item: ItemDep) -> str:
        return item.name

    @inject
    async def _two(*, name: Name, trace: Trace) -> str:
        return f"{name}/{trace}"

    return list(await asyncio.gather(_one(), _two(), _one(), resolve(Name)))


@app.post("/route-then-nested")
async def route_then_nested(item: Item, request: Request) -> list[str]:
    @inject(new_scope=True)
    async def _fresh(*, fresh: ItemDep = Injected) -> str:
        return fresh.name

    # the route took the whole body as the item, so a field embedded under a name is not there
    try:
        await resolve(Name)
    except DependencyResolutionError as exc:
        mismatch = [error["type"] for error in exc.errors]
    else:  # pragma: no cover
        mismatch = []

    return [item.name, await _fresh(), (await request.json())["name"], *mismatch]


@app.post("/form-model")
async def form_model() -> list[str]:
    return [await resolve(LoginDep), await resolve(Fields)]


@app.post("/form-then-json")
async def form_then_json() -> list[str]:
    await resolve(Fields)

    try:
        await resolve(ItemDep)
    except RuntimeError as exc:
        return [str(exc)]

    return []  # pragma: no cover


@app.post("/json-then-form")
async def json_then_form() -> list[str]:
    try:
        await resolve(ItemDep)
    except DependencyResolutionError as exc:
        return [*(error["type"] for error in exc.errors), *(await resolve(Fields)).split("+")]

    return []  # pragma: no cover


@app.post("/content-type")
async def content_type() -> str:
    return (await resolve(ItemDep)).name


@app.get("/no-body")
async def no_body() -> list[str]:
    try:
        await resolve(ItemDep)
    except DependencyResolutionError as exc:
        return [error["type"] for error in exc.errors]

    return []  # pragma: no cover


def test_one_read_for_every_shape() -> None:
    result = client.post("/shapes", json={"name": "a"})

    assert result.status_code == status.HTTP_200_OK
    assert result.json() == ["a", "a", "a", "a"]
    assert counting.reads == [1]


def test_several_body_fields_are_embedded() -> None:
    assert client.post("/pair", json={"name": "b", "extra": 2}).json() == "b:2"
    assert counting.reads == [1]


def test_concurrent_resolves_share_one_read() -> None:
    result = client.post("/concurrent", json={"name": "c"}, headers={"x-trace": "t"})

    assert result.json() == ["c", "c/t", "c", "c"]
    assert counting.reads == [1]


def test_route_body_is_not_read_again_by_a_fresh_scope() -> None:
    assert client.post("/route-then-nested", json={"name": "d"}).json() == ["d", "d", "d", "string_type"]
    assert counting.reads == [1]


def test_form_model_and_fields_share_one_parse() -> None:
    result = client.post("/form-model", data={"user": "e", "password": "f"})

    assert result.json() == ["e/f", "e+f"]
    assert counting.reads == [1]


def test_form_consumes_the_stream_as_in_a_route() -> None:
    # Starlette parses a form from the stream, after which raw bytes are gone - a route reading
    # the body after a form dependency hits the same wall
    [message] = client.post("/form-then-json", data={"user": "g", "password": "h"}).json()

    assert "Stream consumed" in message


def test_json_dependency_leaves_the_form_readable() -> None:
    result = client.post("/json-then-form", data={"user": "i", "password": "j"})

    assert result.json() == ["model_attributes_type", "i", "j"]
    assert counting.reads == [1]


@pytest.mark.parametrize(
    "content_type",
    ["application/json", "application/json; charset=utf-8", "application/vnd.api+json", "APPLICATION/JSON"],
)
def test_json_content_types(content_type: str) -> None:
    result = client.post("/content-type", content=b'{"name": "k"}', headers={"content-type": content_type})

    assert result.json() == "k"


def test_request_without_body() -> None:
    assert client.get("/no-body").json() == ["missing"]
    assert counting.reads == [1]


@pytest.mark.asyncio
async def test_concurrent_resolves_on_a_synthetic_request():
    request = synthetic_request(body={"name": "l"})
    receive = request.receive
    reads = 0

    async def _counting_receive() -> Message:
        nonlocal reads
        reads += 1
        return await receive()

    request._receive = _counting_receive  # noqa: SLF001

    async with push_inject_scope(request=request):
        names = await asyncio.gather(*(resolve(ItemDep, new_scope=True) for _ in range(5)), resolve(Name))

    assert [getattr(name, "name", name) for name in names] == ["l"] * 6
    assert reads == 1
