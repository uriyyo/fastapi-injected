from collections.abc import AsyncIterator, Callable, Iterator
from typing import Any, overload

from typing_extensions import TypeForm

from .deps import HasDependsHook, create_single_dependant, resolve_dependencies
from .scope import inside_inject_scope
from .types import Coro

type _Factory[**P, R] = Callable[P, R] | HasDependsHook[P, R]


@overload
async def resolve[**P, R](
    tp: _Factory[P, Coro[R]],
    /,
    *,
    new_scope: bool = False,
) -> R:
    pass


@overload
async def resolve[**P, R](
    tp: _Factory[P, AsyncIterator[R]],
    /,
    *,
    new_scope: bool = False,
) -> R:
    pass


@overload
async def resolve[**P, R](
    tp: _Factory[P, Iterator[R]],
    /,
    *,
    new_scope: bool = False,
) -> R:
    pass


@overload
async def resolve[**P, R](
    tp: _Factory[P, R],
    /,
    *,
    new_scope: bool = False,
) -> R:
    pass


@overload
async def resolve[R](
    tp: TypeForm[R],
    /,
    *,
    new_scope: bool = False,
) -> R:
    pass


async def resolve(
    tp: Any,
    /,
    *,
    new_scope: bool = False,
) -> Any:

    async with inside_inject_scope(
        new_scope=new_scope,
    ) as inject_scope:
        dependant = create_single_dependant(
            tp,
            path=inject_scope.path_format,
        )

        return await resolve_dependencies(
            dependant,
            inject_scope,
            single=True,
        )


__all__ = [
    "resolve",
]
