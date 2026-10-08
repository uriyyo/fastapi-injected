from typing import Annotated, Any

import pytest
from fastapi import Body, Cookie, Depends, FastAPI, Form, Header, Path, Query, status
from fastapi.testclient import TestClient
from pydantic import BaseModel

from fastapi_injected import (
    DependencyResolutionError,
    Injected,
    NotADependencyError,
    UnnamedParamError,
    bind_deps,
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


app = FastAPI(dependencies=[Depends(init_inject_scope)])
client = TestClient(app)


@app.post("/markers/{item_id}")  # noqa: FAST003 - read by a resolved marker
async def markers() -> list[Any]:
    return [
        await resolve(Header(alias="x-api-key")),
        await resolve(Annotated[str, Header(alias="X-Api-Key")]),
        await resolve(Annotated[int, Query(alias="page")]),
        await resolve(Annotated[int, Path(alias="item_id")]),
        await resolve(Annotated[str, Cookie(alias="sid")]),
        (await resolve(Annotated[Item, Body()])).name,
        await resolve(Annotated[str, Body(alias="name", embed=True)]),
    ]


@app.post("/form")
async def form() -> list[str]:
    return [
        await resolve(Annotated[str, Form(alias="user")]),
        await resolve(Form(alias="user")),
        (await resolve(Annotated[Login, Form()])).user,
    ]


@app.post("/injected")
async def injected() -> list[Any]:
    @inject
    async def _handler(
        *,
        x_api_key: Annotated[str, Header()] = Injected,
        page: Annotated[int, Query()] = Injected,
        item: Annotated[Item, Body()] = Injected,
    ) -> list[Any]:
        return [x_api_key, page, item.name]

    return await _handler()


@app.post("/bound")
async def bound() -> list[Any]:
    async def _handler(key: Annotated[str, Header(alias="x-api-key")], page: Annotated[int, Query()]) -> list[Any]:
        return [key, page]

    return await resolve(bind_deps(_handler))


def test_markers_resolve_on_their_own() -> None:
    result = client.post(
        "/markers/7?page=3",
        json={"name": "a"},
        headers={"x-api-key": "secret"},
        cookies={"sid": "s"},
    )

    assert result.status_code == status.HTTP_200_OK, result.json()
    assert result.json() == ["secret", "secret", 3, 7, "s", "a", "a"]


def test_form_markers() -> None:
    assert client.post("/form", data={"user": "b"}).json() == ["b", "b", "b"]


def test_injected_request_parameters() -> None:
    result = client.post("/injected?page=2", json={"name": "c"}, headers={"x-api-key": "k"})

    assert result.json() == ["k", 2, "c"]


def test_bound_request_parameters() -> None:
    assert client.post("/bound?page=4", headers={"x-api-key": "k"}).json() == ["k", 4]


@pytest.mark.asyncio
async def test_markers_on_a_synthetic_request():
    request = synthetic_request(headers={"X-API-Key": "s"}, query={"page": "5"}, body={"name": "d"})

    async with push_inject_scope(request=request):
        assert await resolve(Header(alias="x-api-key")) == "s"
        assert await resolve(Annotated[int, Query(alias="page")]) == 5
        assert await resolve(Annotated[Item, Body()]) == Item(name="d")


@pytest.mark.asyncio
async def test_marker_validation_errors():
    async with push_inject_scope(request=synthetic_request(query={"page": "x"})):
        with pytest.raises(DependencyResolutionError) as exc_info:
            await resolve(Annotated[int, Query(alias="page")])

        [error] = exc_info.value.errors
        assert (error["type"], error["loc"]) == ("int_parsing", ("query", "page"))

        with pytest.raises(DependencyResolutionError) as exc_info:
            await resolve(Header(alias="x-api-key"))

        [error] = exc_info.value.errors
        assert (error["type"], error["loc"]) == ("missing", ("header", "x-api-key"))


@pytest.mark.parametrize(
    "marker",
    [Header(), Query(), Path(), Cookie(), Form(), Body(embed=True), Annotated[str, Header()]],
    ids=repr,
)
@pytest.mark.asyncio
async def test_marker_without_a_name_is_rejected(marker: Any):
    async with push_inject_scope(request=synthetic_request()):
        with pytest.raises(UnnamedParamError, match="alias"):
            await resolve(marker)


def test_markers_are_not_changed_by_a_resolve() -> None:
    marker = Body()

    assert client.post("/markers/1?page=1", json={"name": "e"}, headers={"x-api-key": "k"}, cookies={"sid": "s"})
    assert marker.alias is None


def test_injected_still_needs_a_dependency() -> None:
    with pytest.raises(NotADependencyError, match="Header"):

        @inject
        async def _handler(*, plain: str = Injected) -> str:
            return plain


def test_request_parameters_stay_the_callers_without_injected() -> None:
    @inject
    async def _handler(
        page: Annotated[int, Query()],
        *,
        key: Annotated[str, Header(alias="x-api-key")] = Injected,
    ) -> str:
        return f"{page}:{key}"

    assert [*_handler.__signature__.parameters] == ["page"]  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_other_metadata_beside_the_marker_is_left_alone():
    async with push_inject_scope(request=synthetic_request(headers={"x-api-key": "s"})):
        assert await resolve(Annotated[str, "documentation", Header(alias="x-api-key")]) == "s"
