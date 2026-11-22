from typing import cast

from ._deps_tp import as_annotation
from ._overrides import ValueOverride
from .types import DepOf


def Given[R](value: R, /) -> DepOf[R]:  # noqa: N802
    # a dependency that was already resolved by whoever built it - constants that hold
    # the same value are the same dependency, so they are cached and overridden alike
    return cast(
        "DepOf[R]",
        as_annotation(ValueOverride(value)),
    )


__all__ = [
    "Given",
]
