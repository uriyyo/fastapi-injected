from functools import partial, wraps
from typing import overload

from .deps import create_dependant, solve_dependencies
from .scope import inside_inject_scope
from .sign import strip_sign
from .types import AsyncFunc, Decorator


@overload
def inject[**P, R](
    func: AsyncFunc[P, R],
    /,
) -> AsyncFunc[P, R]:
    pass


@overload
def inject[**P, R](
    *,
    new_scope: bool = False,
) -> Decorator[P, R]:
    pass


def inject[**P, R](
    func: AsyncFunc[P, R] | None = None,
    /,
    *,
    new_scope: bool = False,
) -> AsyncFunc[P, R] | Decorator[P, R]:
    if func is None:
        return partial(inject, new_scope=new_scope)  # type: ignore[ty:invalid-return-type]

    dependant = create_dependant(func)

    @strip_sign(dependant)
    @wraps(func)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        async with inside_inject_scope(
            new_scope=new_scope,
        ) as inject_scope:
            solved = await solve_dependencies(dependant, inject_scope)

            for key, value in solved.items():
                kwargs.setdefault(key, value)

            return await func(*args, **kwargs)

    return wrapper


__all__ = [
    "inject",
]
