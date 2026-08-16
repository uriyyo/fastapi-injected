import pytest

from fastapi_injected import push_inject_scope

pytestmark = pytest.mark.asyncio


async def test_scope_without_request_is_synthetic():
    async with push_inject_scope() as scope:
        assert scope.synthetic


async def test_nested_scope_keeps_request_synthetic():
    async with push_inject_scope() as outer, push_inject_scope(request=outer.request) as inner:
        assert inner.synthetic
