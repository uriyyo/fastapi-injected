from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import field
from typing import Any

from ._dataclass import MakeDataclass
from ._overrides import FactoryOverride, Overrides, ValueOverride, normalize_overrides
from .scope import InjectScope
from .types import HasDependencyOverrides


class OverridesProvider(MakeDataclass):
    dependency_overrides: Mapping[Any, Any] = field(default_factory=dict)


@contextmanager
def push_overrides(
    overrides: Overrides | None = None,
    /,
    *,
    provider: HasDependencyOverrides | None = None,
) -> Iterator[InjectScope]:
    scope = InjectScope.current() or InjectScope()

    with scope.override(overrides, provider=provider) as child:
        yield child


__all__ = [
    "FactoryOverride",
    "Overrides",
    "OverridesProvider",
    "ValueOverride",
    "normalize_overrides",
    "push_overrides",
]
