from dataclasses import dataclass

import pytest

from fastapi_injected import Dep, push_inject_scope, solve

pytestmark = pytest.mark.asyncio


@dataclass
class Foo:
    pass


@dataclass
class Bar:
    foo: Dep[Foo]


async def test_solve():
    bar = await solve(Bar)

    assert isinstance(bar, Bar)
    assert isinstance(bar.foo, Foo)


async def test_solve_reuse_cache():
    async with push_inject_scope():
        b1 = await solve(Bar)
        b2 = await solve(Bar)

        assert b1 is b2
