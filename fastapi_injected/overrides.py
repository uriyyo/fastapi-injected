from collections import ChainMap
from collections.abc import AsyncGenerator, Awaitable, Callable, Generator, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from ._deps_tp import is_dep, unwrap_dep_dependency
from .deps import get_inject_dependency_override_provider, set_inject_dependency_override_provider
from .scope import current_inject_scope
from .types import HasDependencyOverrides


class NonFreshScopeError(Exception):
    def __init__(self) -> None:
        super().__init__("push_overrides requires a fresh scope")


def _get_current_overrides() -> Iterator[Mapping[Any, Any]]:
    obj = get_inject_dependency_override_provider()

    if isinstance(obj, HasDependencyOverrides):
        yield obj.dependency_overrides


def _get_override_key(tp: Any) -> Any:
    if is_dep(tp):
        value = unwrap_dep_dependency(tp)

        if value is not None:
            return value

    return tp


@dataclass
class _OverridesProvider:
    dependency_overrides: Mapping[Any, Any]


def _create_async_resolver[T](val: T) -> Callable[[], Awaitable[T]]:
    async def _resolver() -> T:
        return val

    return _resolver


def _create_resolver[T](val: T, /) -> Any:
    match val:
        case ValueOverride(value):
            return _create_async_resolver(value)
        case FactoryOverride(factory):
            return factory
        case _:
            return _create_async_resolver(val)


@dataclass
class ValueOverride[T]:
    value: T


@dataclass
class FactoryOverride[**P, T]:
    factory: Callable[P, T | Awaitable[T] | Generator[T] | AsyncGenerator[T]]


type Overrides = dict[Any, Any | ValueOverride | FactoryOverride]


def _enforce_fresh_scope() -> None:
    scope = current_inject_scope()

    if scope is None:
        return

    if scope.dependency_cache:
        raise NonFreshScopeError


@contextmanager
def push_overrides(
    overrides: Overrides,
    /,
    *,
    require_fresh_scope: bool = True,
) -> Iterator[None]:

    if require_fresh_scope:
        _enforce_fresh_scope()

    deps = ChainMap(
        {_get_override_key(k): _create_resolver(v) for k, v in overrides.items()},
        *_get_current_overrides(),  # type: ignore[ty:invalid-argument-type]
    )

    with set_inject_dependency_override_provider(
        _OverridesProvider(deps),
    ):
        yield


__all__ = [
    "FactoryOverride",
    "ValueOverride",
    "push_overrides",
]
