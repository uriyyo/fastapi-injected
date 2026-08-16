from collections import ChainMap
from collections.abc import Callable, Iterator, MutableMapping
from typing import TYPE_CHECKING, Any, overload

from ._dataclass import MakeDataclass
from ._deps_tp import is_dep, unwrap_dep_dependency
from .types import DepDecl, DepReturn, HasDependencyOverrides


class ValueOverride[T](MakeDataclass):
    value: T

    async def __call__(self) -> T:
        return self.value


class FactoryOverride[**P, T](MakeDataclass):
    factory: Callable[[], DepReturn[T]]

    if TYPE_CHECKING:

        @overload
        def __init__(self, factory: DepDecl[P, T], /) -> None: ...

        @overload
        def __init__(self, factory: Callable[P, T], /) -> None: ...

        def __init__(self, factory: Callable[P, DepReturn[T]], /) -> None: ...


type Overrides = dict[Any, Any | ValueOverride | FactoryOverride]


def _get_override_key(tp: Any) -> Any:
    if is_dep(tp):
        value = unwrap_dep_dependency(tp)

        if value is not None:
            return value

    return tp


def _create_resolver[T](val: T, /) -> Any:
    match val:
        case ValueOverride():
            return val
        case FactoryOverride(factory):
            return factory
        case _:
            return ValueOverride(val)


def _provider_overrides(obj: Any | None, /) -> Iterator[MutableMapping[Any, Any]]:
    if obj is None:
        return

    if isinstance(obj, HasDependencyOverrides):
        yield obj.dependency_overrides


def normalize_overrides(
    overrides: Overrides | None = None,
    /,
    *,
    provider: HasDependencyOverrides | None = None,
) -> MutableMapping[Any, Any]:
    return ChainMap(
        {_get_override_key(key): _create_resolver(value) for key, value in (overrides or {}).items()},
        *_provider_overrides(provider),
    )


__all__ = [
    "FactoryOverride",
    "Overrides",
    "ValueOverride",
    "normalize_overrides",
]
