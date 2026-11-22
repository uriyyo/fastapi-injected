import gc
import weakref
from contextlib import nullcontext
from functools import wraps
from typing import Any

import pytest
from fastapi import Depends
from fastapi.dependencies import models

from fastapi_injected import injection_ctx, resolve
from fastapi_injected._calls import _is_static_call, is_static_annotation, runtime_calls

pytestmark = pytest.mark.asyncio


def module_level() -> int:
    return 1


def _closure() -> Any:
    def inner() -> int:  # pragma: no cover
        return 1

    return inner


def _wrapped() -> Any:
    @wraps(module_level)
    def wrapper() -> int:  # pragma: no cover
        return 1

    return wrapper


class Unhashable:
    __hash__ = None  # type: ignore[assignment]

    def __call__(self) -> int:
        return 1


@pytest.mark.parametrize(
    ("call", "expected"),
    [
        pytest.param(module_level, True, id="function"),
        pytest.param(Unhashable, True, id="class"),
        pytest.param(len, True, id="builtin"),
        pytest.param(_closure(), False, id="closure"),
        # `functools.wraps` copies the name of a function written at module level
        pytest.param(_wrapped(), False, id="wrapped-closure"),
        pytest.param({}.get, False, id="bound-builtin"),
        pytest.param(Unhashable(), False, id="instance"),
    ],
)
async def test_what_counts_as_written_in_source(call: Any, expected: bool):
    assert _is_static_call(call) is expected


async def test_an_annotation_without_metadata_is_not_static():
    assert not is_static_annotation(int)


class One:
    def __call__(self) -> int:
        return 1


class Defaulted:
    # a dependency that is an object, written as a default rather than in the annotation
    def __init__(self, value: int) -> None:
        self.value = value

    async def __call__(self, one: int = Depends(One())) -> int:
        return self.value + one


async def test_a_dependency_written_as_a_default_is_resolved():
    async with injection_ctx():
        assert await resolve(Defaulted(41)) == 42


@pytest.mark.parametrize(("inside", "released"), [(True, True), (False, False)])
async def test_fastapi_keeps_a_runtime_call_classified_only_outside_runtime_calls(inside: bool, released: bool):
    call = One()
    ref = weakref.ref(call)

    with runtime_calls() if inside else nullcontext():
        models._is_coroutine_callable(call)  # noqa: SLF001

    del call
    gc.collect()

    assert (ref() is None) is released


async def test_the_call_classifiers_are_patched_once():
    await resolve(Defaulted(1))
    patched = models._is_gen_callable_cached  # noqa: SLF001

    await resolve(Defaulted(1))

    assert models._is_gen_callable_cached is patched  # noqa: SLF001
    # what it wraps is FastAPI's own lru cache, not another patch
    assert not getattr(patched.__wrapped__, "__fastapi_injected_patched__", False)
    assert patched.cache_info().maxsize == models._CALLABLE_CLASSIFICATION_CACHE_SIZE  # noqa: SLF001
