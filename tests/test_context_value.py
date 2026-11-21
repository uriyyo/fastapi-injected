from typing import Annotated

import pytest
from fastapi import Depends, FastAPI, Query
from fastapi.testclient import TestClient

from fastapi_injected import (
    ContextValue,
    NoInjectionContextError,
    add_injection,
    injection_ctx,
    push_overrides,
    resolve,
)

pytestmark = pytest.mark.asyncio

page_size = ContextValue[int]("page_size", default=10)
tenant = ContextValue[str]("tenant")


async def test_a_value_is_read_where_it_was_set():
    async with injection_ctx():
        assert page_size.get() == 10

        page_size.set(20)
        assert page_size.get() == 20


async def test_nested_contexts_read_the_value_without_changing_it():
    async with injection_ctx():
        tenant.set("acme")

        async with injection_ctx():
            assert tenant.get() == "acme"
            tenant.set("other")
            assert tenant.get() == "other"

        with push_overrides():
            tenant.set("overridden")

        assert tenant.get() == "acme"


async def test_a_closed_context_takes_its_values_with_it():
    async with injection_ctx():
        tenant.set("acme")

    async with injection_ctx():
        with pytest.raises(LookupError, match="tenant is not set"):
            tenant.get()


async def test_outside_a_context():
    assert page_size.get() == 10

    with pytest.raises(LookupError):
        tenant.get()

    with pytest.raises(NoInjectionContextError):
        tenant.set("acme")


def set_tenant(x_tenant: Annotated[str, Query()] = "public") -> None:
    tenant.set(x_tenant)


async def read_tenant() -> str:
    return tenant.get()


app = FastAPI()
add_injection(app)


@app.get("/", dependencies=[Depends(set_tenant)])
async def route() -> list[str]:
    return [tenant.get(), await resolve(read_tenant)]


def test_a_value_set_by_a_dependency_is_seen_by_the_route():
    client = TestClient(app)

    assert client.get("/", params={"x_tenant": "acme"}).json() == ["acme", "acme"]
    assert client.get("/").json() == ["public", "public"]
