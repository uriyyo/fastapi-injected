import gc
import weakref
from dataclasses import dataclass

import pytest
from fastapi import params

from fastapi_injected import Dep, Injected, clear_dependant_cache, inject, push_inject_scope, resolve
from fastapi_injected.deps import _create_annotation_dependant

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
