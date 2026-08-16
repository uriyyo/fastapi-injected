from collections.abc import Callable
from dataclasses import Field, dataclass, field
from typing import TYPE_CHECKING, Any, dataclass_transform

_DATACLASS_KEYS = frozenset(
    {
        "init",
        "repr",
        "eq",
        "order",
        "unsafe_hash",
        "frozen",
        "match_args",
        "kw_only",
        "slots",
        "weakref_slot",
    },
)


def _smart_hash(base_hash: Callable[[Any], int], /) -> Callable[[Any], int]:
    def _hash(obj: Any, /) -> int:
        try:
            return base_hash(obj)
        except TypeError:
            return object.__hash__(obj)

    return _hash


@dataclass_transform(field_specifiers=(field, Field))
class MakeDataclass:
    def __init_subclass__(cls, **kwargs: Any) -> None:
        options = {key: kwargs.pop(key) for key in list(kwargs) if key in _DATACLASS_KEYS}

        super().__init_subclass__(**kwargs)

        # a dataclass with `eq` and without `frozen` is unhashable, and these are meant
        # to be usable as cache keys, so they keep a hash built from their fields
        if options.get("eq", True) and not options.get("frozen", False):
            options.setdefault("unsafe_hash", True)

        dataclass(cls, **options)

        cls.__hash__ = _smart_hash(cls.__hash__ or object.__hash__)  # type: ignore[ty:invalid-assignment]

    if TYPE_CHECKING:

        def __hash__(self) -> int:
            pass


__all__ = [
    "MakeDataclass",
]
