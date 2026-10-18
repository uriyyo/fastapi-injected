from typing import Annotated

import pytest
from fastapi import Depends, FastAPI, Request

from fastapi_injected import injection_ctx, resolve

pytestmark = pytest.mark.asyncio


async def test_ctx_without_request_is_synthetic():
    async with injection_ctx() as ctx:
        assert ctx.synthetic


async def test_nested_ctx_keeps_request_synthetic():
    async with injection_ctx() as outer, injection_ctx(request=outer.request) as inner:
        assert inner.synthetic


async def test_synthetic_request_answers_what_a_dependency_reads():
    async with injection_ctx() as ctx:
        request = ctx.bound_request

        assert request.method == "GET"
        assert str(request.url) == "/"
        assert request.path_params == {}
        assert request.client is None
        assert not request.headers


async def test_synthetic_request_says_what_is_missing():
    async with injection_ctx() as ctx:
        with pytest.raises(KeyError, match="not part of a synthetic request"):
            _ = ctx.bound_request.app


async def app_answer(request: Request) -> int:
    return request.app.state.answer


AppAnswer = Annotated[int, Depends(app_answer)]


async def test_app_can_be_given_to_a_ctx():
    app = FastAPI()
    app.state.answer = 42

    async with injection_ctx(app=app):
        assert await resolve(AppAnswer) == 42
