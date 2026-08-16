from typing import Annotated

import pytest
from fastapi import Depends, FastAPI, Request

from fastapi_injected import push_inject_scope, resolve

pytestmark = pytest.mark.asyncio


async def test_scope_without_request_is_synthetic():
    async with push_inject_scope() as scope:
        assert scope.synthetic


async def test_nested_scope_keeps_request_synthetic():
    async with push_inject_scope() as outer, push_inject_scope(request=outer.request) as inner:
        assert inner.synthetic


async def test_synthetic_request_answers_what_a_dependency_reads():
    async with push_inject_scope() as scope:
        request = scope.bound_request

        assert request.method == "GET"
        assert str(request.url) == "/"
        assert request.path_params == {}
        assert request.client is None
        assert not request.headers


async def test_synthetic_request_says_what_is_missing():
    async with push_inject_scope() as scope:
        with pytest.raises(KeyError, match="not part of a synthetic request"):
            _ = scope.bound_request.app


async def app_answer(request: Request) -> int:
    return request.app.state.answer


AppAnswer = Annotated[int, Depends(app_answer)]


async def test_app_can_be_given_to_a_scope():
    app = FastAPI()
    app.state.answer = 42

    async with push_inject_scope(app=app):
        assert await resolve(AppAnswer) == 42
