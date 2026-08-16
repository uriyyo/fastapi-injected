from typing import Annotated, Any, cast

from fastapi import Depends

from ._dataclass import MakeDataclass
from .types import DepOf


class _Constant[R](MakeDataclass):
    value: R

    async def __call__(self) -> R:
        return self.value


def Given[R](value: R, /) -> DepOf[R]:  # noqa: N802
    # a dependency that was already resolved by whoever built it - constants that hold
    # the same value are the same dependency, so they are cached and overridden alike
    return cast("DepOf[R]", Annotated[Any, Depends(_Constant(value))])


__all__ = [
    "Given",
]
