from collections.abc import Callable
from typing import Any, overload

from typing_extensions import TypeForm

from .ctx import ensure_injection_ctx
from .deps import HasDependsHook, open_dependant, solve_value
from .types import DepDecl, DepShape

type _Factory[**P, R] = Callable[P, R] | HasDependsHook[P, R]


@overload
async def resolve[**P, R](
    tp: DepDecl[P, R] | HasDependsHook[P, DepShape[R]],
    /,
    *,
    new_ctx: bool = False,
) -> R:
    pass


@overload
async def resolve[**P, R](
    tp: _Factory[P, R],
    /,
    *,
    new_ctx: bool = False,
) -> R:
    pass


@overload
async def resolve[R](
    tp: TypeForm[R],
    /,
    *,
    new_ctx: bool = False,
) -> R:
    pass


async def resolve(
    tp: Any,
    /,
    *,
    new_ctx: bool = False,
) -> Any:

    async with ensure_injection_ctx(
        new_ctx=new_ctx,
    ) as ctx:
        with open_dependant(
            tp,
            path=ctx.path_format,
        ) as dependant:
            return await solve_value(dependant, ctx)


__all__ = [
    "resolve",
]
