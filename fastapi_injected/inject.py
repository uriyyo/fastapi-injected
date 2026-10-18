import inspect
from functools import partial, wraps
from typing import overload

from .ctx import ensure_injection_ctx
from .deps import create_dependant, solve_arguments
from .signature import Signature
from .types import AsyncDecorator, AsyncFunc


@overload
def inject[**P, R](
    func: AsyncFunc[P, R],
    /,
) -> AsyncFunc[P, R]:
    pass


@overload
def inject[**P, R](
    *,
    new_ctx: bool = False,
) -> AsyncDecorator[P, R]:
    pass


def inject[**P, R](
    func: AsyncFunc[P, R] | None = None,
    /,
    *,
    new_ctx: bool = False,
) -> AsyncFunc[P, R] | AsyncDecorator[P, R]:
    if func is None:
        return partial(inject, new_ctx=new_ctx)  # type: ignore[ty:invalid-return-type]

    dependant = create_dependant(func)

    @wraps(func)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        async with ensure_injection_ctx(
            new_ctx=new_ctx,
        ) as ctx:
            solved = await solve_arguments(dependant, ctx)

            for key, value in solved.items():
                kwargs.setdefault(key, value)

            return await func(*args, **kwargs)

    # plain inspect.signature: the wrapper's globals cannot resolve the function's string annotations
    return Signature.of(inspect.signature(wrapper)).strip(dependant).apply(wrapper)


__all__ = [
    "inject",
]
