from collections.abc import Generator, Mapping, MutableMapping
from contextlib import contextmanager
from dataclasses import field
from typing import Any, Protocol

from ._dataclass import MakeDataclass
from ._overrides import FactoryOverride, Overrides, ValueOverride, normalize_overrides
from .ctx import InjectionContext, OverrideBlock
from .types import HasDependencyOverrides


class OverridesProvider(MakeDataclass):
    dependency_overrides: Mapping[Any, Any] = field(default_factory=dict)


def push_overrides(
    overrides: Overrides | None = None,
    /,
    *,
    provider: HasDependencyOverrides | None = None,
) -> OverrideBlock[InjectionContext]:
    ctx = InjectionContext.current() or InjectionContext()

    return ctx.override(overrides, provider=provider)


class HasMutableOverrides(Protocol):
    @property
    def dependency_overrides(self) -> MutableMapping[Any, Any]: ...


@contextmanager
def override_app(provider: HasMutableOverrides, overrides: Mapping[Any, Any], /) -> Generator[None]:
    previous = {**provider.dependency_overrides}
    provider.dependency_overrides.update(overrides)

    try:
        yield
    finally:
        provider.dependency_overrides.clear()
        provider.dependency_overrides.update(previous)


__all__ = [
    "FactoryOverride",
    "OverrideBlock",
    "Overrides",
    "OverridesProvider",
    "ValueOverride",
    "normalize_overrides",
    "override_app",
    "push_overrides",
]
