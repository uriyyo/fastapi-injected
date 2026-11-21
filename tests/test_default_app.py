import asyncio

import pytest
from fastapi import FastAPI, Request

from fastapi_injected import Dep, Injected, add_injection, inject, injection_ctx, resolve, set_default_app

pytestmark = pytest.mark.asyncio


class Service:
    name = "real"


class FakeService(Service):
    name = "fake"


@pytest.fixture
def app() -> FastAPI:
    app = FastAPI()
    app.dependency_overrides[Service] = FakeService
    add_injection(app)

    return app


async def test_inject_outside_a_request_uses_the_default_apps_overrides(app: FastAPI) -> None:
    @inject
    async def handler(*, service: Dep[Service] = Injected) -> str:
        return service.name

    assert await handler() == "fake"


async def test_the_default_app_is_the_request_app(app: FastAPI) -> None:
    async def current_app(request: Request) -> FastAPI:
        return request.app

    assert await resolve(current_app) is app


async def test_an_explicit_app_wins_over_the_default(app: FastAPI) -> None:
    other = FastAPI()

    async with injection_ctx(app=other):
        assert (await resolve(Service)).name == "real"


async def test_without_a_default_no_overrides_apply(app: FastAPI) -> None:
    set_default_app(None)

    assert (await resolve(Service)).name == "real"


async def test_the_last_app_given_to_add_injection_is_the_default(app: FastAPI) -> None:
    add_injection(FastAPI())

    assert (await resolve(Service)).name == "real"


async def test_a_default_set_inside_a_task_stays_in_that_task(app: FastAPI) -> None:
    async def child() -> str:
        set_default_app(FastAPI())
        return (await resolve(Service)).name

    assert await asyncio.create_task(child()) == "real"
    assert (await resolve(Service)).name == "fake"


async def test_a_default_set_with_with_is_put_back_after_the_block(app: FastAPI) -> None:
    with set_default_app(FastAPI()) as other:
        assert other is not app
        assert (await resolve(Service)).name == "real"

    assert (await resolve(Service)).name == "fake"
