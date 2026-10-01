import inspect
from functools import wraps
from typing import Annotated, Any

import pytest
from fastapi import Depends

from fastapi_injected import push_inject_scope, resolve
from fastapi_injected._calls import CallProxy, DetachedOverrides, is_static_annotation, is_static_call

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
    assert is_static_call(call) is expected


async def test_an_annotation_without_metadata_is_not_static():
    assert not is_static_annotation(int)


async def test_a_released_proxy_lets_go_of_its_call():
    proxy = CallProxy(module_level, [])
    proxy.release()

    assert proxy.call is None
    assert not hasattr(proxy, "__wrapped__")
    assert proxy == proxy  # noqa: PLR0124
    assert proxy != module_level


async def test_a_proxy_of_an_unhashable_call_is_hashed_by_identity():
    call = Unhashable()
    proxy = CallProxy(call, [])

    assert hash(proxy) == id(call)
    assert proxy() == 1


class One:
    def __call__(self) -> int:
        return 1


class Defaulted:
    # a dependency that is an object, written as a default rather than in the annotation
    def __init__(self, value: int) -> None:
        self.value = value

    async def __call__(self, one: int = Depends(One())) -> int:
        return self.value + one


async def test_a_dependency_written_as_a_default_is_detached_too():
    async with push_inject_scope():
        assert await resolve(Defaulted(41)) == 42


async def test_a_proxy_shows_fastapi_the_signature_it_stands_for():
    async def call(value: Annotated[int, Depends(module_level)]) -> int:  # pragma: no cover
        return value

    # FastAPI reads the parameters only, its own typed signature drops the return annotation
    assert inspect.signature(CallProxy(call, [])).parameters == inspect.signature(call).parameters


async def test_detached_overrides_hand_out_what_was_made_at_runtime_behind_a_proxy():
    value = One()
    proxies: list[CallProxy] = []
    overrides = DetachedOverrides({module_level: value, One: module_level}, proxies)

    assert overrides.dependency_overrides is overrides
    assert (list(overrides), len(overrides), bool(overrides)) == ([module_level, One], 2, True)
    assert overrides[One] is module_level  # written in source, nothing to detach
    assert overrides[module_level] is overrides[module_level]
    assert overrides[module_level] == value
    assert proxies == [value]
    assert not DetachedOverrides({}, [])
