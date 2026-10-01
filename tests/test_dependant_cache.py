import gc
import weakref
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Annotated, Any

import pytest
from anyio import to_thread
from fastapi import Depends, params

from fastapi_injected import (
    Dep,
    FactoryOverride,
    Given,
    Injected,
    MakeInjected,
    bind_deps,
    clear_dependant_cache,
    inject,
    push_inject_scope,
    push_overrides,
    resolve,
)
from fastapi_injected.deps import _create_annotation_dependant
from fastapi_injected.types import DepOf

pytestmark = pytest.mark.asyncio


@dataclass
class Foo:
    pass


def foo_dep() -> Foo:
    return Foo()


class Hook:
    # an object that brings its own `Depends` and carries per-request data with it
    def __init__(self, payload: list[int]) -> None:
        self.payload = payload

    def __call__(self) -> Foo:  # pragma: no cover
        raise AssertionError("should be resolved through __get_depends__")

    def __get_depends__(self) -> params.Depends:
        return params.Depends(foo_dep)


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    clear_dependant_cache()


async def _resolve_through_hooks(count: int) -> list[weakref.ref[Hook]]:
    refs = []

    for _ in range(count):
        hook = Hook([0] * 100)
        refs.append(weakref.ref(hook))

        async with push_inject_scope():
            await resolve(hook)

    return refs


async def test_dependency_holders_are_not_kept_alive():
    refs = await _resolve_through_hooks(3)

    gc.collect()

    assert not [ref for ref in refs if ref() is not None]


async def test_holders_that_resolve_the_same_way_share_an_entry():
    await _resolve_through_hooks(3)

    info = _create_annotation_dependant.cache_info()

    assert (info.hits, info.misses, info.currsize) == (2, 1, 1)


async def test_clear_dependant_cache():
    await _resolve_through_hooks(1)
    assert _create_annotation_dependant.cache_info().currsize == 1

    clear_dependant_cache()

    assert _create_annotation_dependant.cache_info().currsize == 0


async def test_decorated_functions_are_not_kept_alive():
    refs = []

    for _ in range(3):

        @inject
        async def func(*, foo: Dep[Foo] = Injected) -> Foo:  # pragma: no cover
            return foo

        refs.append(weakref.ref(func))
        del func

    gc.collect()

    assert not [ref for ref in refs if ref() is not None]


class Payload:
    # stands in for what a request hands over - an actor, a record, a repository
    pass


class Owns(MakeInjected):
    payload: DepOf[Payload]
    foo: DepOf[Foo]

    async def __call__(self, payload: Payload, foo: Foo) -> Payload:
        return payload


class Resolver:
    # brings its own `Depends` on itself, the way a permission resolver does
    def __init__(self, payload: Payload) -> None:
        self.payload = payload

    async def __call__(self, foo: Annotated[Foo, Depends(foo_dep)]) -> Payload:
        return self.payload

    def __get_depends__(self) -> params.Depends:
        return params.Depends(self)


async def _describe(payload: Payload, foo: Foo) -> Payload:
    return payload


FooDep = Annotated[Foo, Depends(foo_dep)]

RUNTIME_DEPS: dict[str, Callable[[Payload], Any]] = {
    "given": Given,
    "injected": lambda payload: Owns(payload=Given(payload), foo=FooDep),
    "depends-hook": Resolver,
    "bound": lambda payload: bind_deps(_describe, Given(payload), FooDep),
}


@pytest.mark.parametrize("make", RUNTIME_DEPS.values(), ids=RUNTIME_DEPS.keys())
async def test_values_resolved_at_runtime_are_not_kept_alive(make: Callable[[Payload], Any]):
    refs = []

    for _ in range(3):
        payload = Payload()
        refs.append(weakref.ref(payload))

        async with push_inject_scope():
            assert await resolve(make(payload)) is payload

        del payload

    gc.collect()

    assert not [ref for ref in refs if ref() is not None]


@pytest.mark.parametrize("make", RUNTIME_DEPS.values(), ids=RUNTIME_DEPS.keys())
async def test_values_resolved_under_overrides_are_not_kept_alive(make: Callable[[Payload], Any]):
    # with overrides in place FastAPI analyses every dependency again on each resolve
    refs = []

    for _ in range(3):
        payload = Payload()
        refs.append(weakref.ref(payload))

        with push_overrides({foo_dep: Foo()}):
            assert await resolve(make(payload)) is payload

        del payload

    gc.collect()

    assert not [ref for ref in refs if ref() is not None]


@pytest.mark.parametrize("make", RUNTIME_DEPS.values(), ids=RUNTIME_DEPS.keys())
async def test_values_resolved_at_runtime_are_not_cached(make: Callable[[Payload], Any]):
    for _ in range(3):
        await resolve(make(Payload()))

    assert _create_annotation_dependant.cache_info().currsize == 0


class Opened(Resolver):
    async def __call__(self, foo: Annotated[Foo, Depends(foo_dep)]) -> AsyncIterator[list[Payload]]:  # ty: ignore[invalid-method-override]
        opened = [self.payload]
        yield opened
        opened.clear()


async def test_a_runtime_generator_is_torn_down_with_its_scope():
    payload = Payload()

    async with push_inject_scope():
        opened = await resolve(Opened(payload))
        assert opened == [payload]

    assert opened == []


async def test_a_runtime_dependency_shares_the_scope_cache_with_static_ones():
    async with push_inject_scope():
        foo = await resolve(FooDep)

        # the runtime dependency hands its `foo` back through the same scope cache
        class Peek(MakeInjected):
            foo: DepOf[Foo]

            async def __call__(self, foo: Foo) -> Foo:
                return foo

        assert await resolve(Peek(foo=FooDep)) is foo


OVERRIDES: dict[str, Callable[[Payload], Any]] = {
    "value": lambda payload: payload,
    "factory": lambda payload: FactoryOverride(lambda: payload),
}


@pytest.mark.parametrize("make", OVERRIDES.values(), ids=OVERRIDES.keys())
async def test_overrides_are_not_kept_alive_past_their_block(make: Callable[[Payload], Any]):
    refs = []

    for _ in range(3):
        payload = Payload()
        refs.append(weakref.ref(payload))

        with push_overrides({Payload: make(payload)}):
            assert await resolve(Payload) is payload

        del payload

    # an idle worker thread holds the last result it computed until it runs again
    await to_thread.run_sync(lambda: None)
    gc.collect()

    assert not [ref for ref in refs if ref() is not None]
