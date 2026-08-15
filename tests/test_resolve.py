from dataclasses import dataclass

import pytest
from fastapi import Depends, params

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


@dataclass(frozen=True)
class DependsHook:
    use_cache: bool = True

    def __call__(self) -> Bar:  # pragma: no cover
        raise AssertionError("should be resolved via __get_depends__")

    def __get_depends__(self) -> params.Depends:
        return Depends(Bar, use_cache=self.use_cache)


async def test_resolve_depends_hook():
    bar = await resolve(DependsHook())

    assert isinstance(bar, Bar)
    assert isinstance(bar.foo, Foo)


async def test_resolve_depends_hook_reuse_cache():
    async with push_inject_scope():
        b1 = await resolve(DependsHook())
        b2 = await resolve(DependsHook())

        assert b1 is b2


async def test_resolve_depends_hook_no_cache():
    async with push_inject_scope():
        b1 = await resolve(DependsHook(use_cache=False))
        b2 = await resolve(DependsHook(use_cache=False))

        assert b1 is not b2
