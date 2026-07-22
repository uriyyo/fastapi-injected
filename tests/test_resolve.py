from dataclasses import dataclass

import pytest

from fastapi_injected import Dep, push_inject_scope, resolve

pytestmark = pytest.mark.asyncio


@dataclass
class Foo:
    pass


@dataclass
class Bar:
    foo: Dep[Foo]


async def test_resolve():
    bar = await resolve(Bar)

    assert isinstance(bar, Bar)
    assert isinstance(bar.foo, Foo)


async def test_resolve_reuse_cache():
    async with push_inject_scope():
        b1 = await resolve(Bar)
        b2 = await resolve(Bar)

        assert b1 is b2
