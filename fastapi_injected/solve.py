from typing_extensions import TypeForm

from .deps import create_single_dependant, solve_dependencies
from .scope import inside_inject_scope


async def solve[R](
    tp: TypeForm[R],
    *,
    new_scope: bool = False,
) -> R:
    dependant = create_single_dependant(tp)

    async with inside_inject_scope(
        new_scope=new_scope,
    ) as inject_scope:
        return await solve_dependencies(
            dependant,
            inject_scope,
            single=True,
        )


__all__ = [
    "solve",
]
