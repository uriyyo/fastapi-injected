from collections.abc import AsyncIterator, Iterator
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


def plain_factory() -> Foo:
    return Foo()


async def coro_factory() -> Foo:
    return Foo()


def sync_gen_factory() -> Iterator[Foo]:
    yield Foo()


async def async_gen_factory() -> AsyncIterator[Foo]:
    yield Foo()


@pytest.mark.parametrize(
    "factory",
    [
        Foo,
        plain_factory,
        coro_factory,
        sync_gen_factory,
        async_gen_factory,
    ],
)
async def test_resolve_factory(factory):
    assert isinstance(await resolve(factory), Foo)


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


class CallableFactory:
    def __init__(self) -> None:
        self.closed = False

    def __call__(self) -> Iterator[Foo]:
        yield Foo()
        self.closed = True


async def test_resolve_callable_object_generator():
    factory = CallableFactory()

    assert isinstance(await resolve(factory), Foo)
    # fastapi looks through `__call__`, so it is torn down like any generator dependency
    assert factory.closed


def list_factory() -> list[Foo]:
    return [Foo()]


async def test_resolve_collection_factory():
    # a collection is the value, not something to iterate for one
    assert isinstance(await resolve(list_factory), list)
