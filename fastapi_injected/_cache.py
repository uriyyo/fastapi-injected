from collections.abc import Collection, Iterator, Mapping, MutableMapping, Sequence
from dataclasses import field
from typing import Any

from fastapi.dependencies.models import Dependant
from fastapi.types import DependencyCacheKey

from ._dataclass import MakeDataclass
from .types import DependencyCache


def overridden_calls(dependant: Dependant, overrides: Collection[Any], /) -> frozenset[Any]:
    if not overrides:
        return frozenset()

    overridden: set[Any] = set()

    def _visit(dep: Dependant, /) -> bool:
        is_overridden = dep.call is not None and dep.call in overrides

        for sub_dep in dep.dependencies:
            is_overridden = _visit(sub_dep) or is_overridden

        if is_overridden and dep.call is not None:
            overridden.add(dep.call)

        return is_overridden

    _visit(dependant)
    return frozenset(overridden)


class ScopeCache(MakeDataclass, MutableMapping[DependencyCacheKey, Any]):
    cache: DependencyCache
    fallbacks: Sequence[tuple[Mapping[DependencyCacheKey, Any], frozenset[Any]]] = field(default_factory=tuple)

    def _visible_fallbacks(self, key: DependencyCacheKey, /) -> Iterator[Mapping[DependencyCacheKey, Any]]:
        call, *_ = key

        for cache, overridden in self.fallbacks:
            if call not in overridden:
                yield cache

    def __getitem__(self, key: DependencyCacheKey) -> Any:
        try:
            return self.cache[key]
        except KeyError:
            pass

        for cache in self._visible_fallbacks(key):
            try:
                return cache[key]
            except KeyError:
                continue

        raise KeyError(key)

    def __setitem__(self, key: DependencyCacheKey, value: Any) -> None:
        self.cache[key] = value

    def __delitem__(self, key: DependencyCacheKey) -> None:
        del self.cache[key]

    def __iter__(self) -> Iterator[DependencyCacheKey]:
        seen = set(self.cache)
        yield from seen

        for cache, overridden in self.fallbacks:
            for key in cache:
                call, *_ = key

                if key not in seen and call not in overridden:
                    seen.add(key)
                    yield key

    def __len__(self) -> int:
        return sum(1 for _ in self)


__all__ = [
    "ScopeCache",
    "overridden_calls",
]
