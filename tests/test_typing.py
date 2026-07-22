from typing import TYPE_CHECKING

from fastapi_injected import Dep, DepFactory, Inejected, inject, solve

from .deps import Child, Container, ContextState, ctx_dep

if TYPE_CHECKING:
    from ty_extensions import static_assert
    from ty_extensions._internal import TypeOf, is_equivalent_to


@inject
async def func(
    a: int,
    *,
    container: Dep[Container] = Inejected,
) -> int:
    static_assert(is_equivalent_to(TypeOf[container], Container))
    static_assert(is_equivalent_to(TypeOf[container.child], Child))
    static_assert(is_equivalent_to(TypeOf[container.ctx], ContextState))

    return a + 10


async def solve_test() -> None:
    container = await solve(Container)

    static_assert(is_equivalent_to(TypeOf[container], Container))


if TYPE_CHECKING:
    static_assert(is_equivalent_to(Dep[Container], Container))
    static_assert(is_equivalent_to(DepFactory[ContextState, ctx_dep], ContextState))
