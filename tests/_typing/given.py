from typing_extensions import TypeForm

from fastapi_injected import Given, resolve
from fastapi_injected.types import DepOf

from .deps import (
    ContextState,
    NonPydanticType,
    TypeOf,
    is_equivalent_to,
    static_assert,
)


def _constants(value: int) -> None:
    # a constant is a marker for what it holds, whatever that is
    static_assert(is_equivalent_to(TypeOf[Given(value)], TypeForm[int]))
    static_assert(is_equivalent_to(TypeOf[Given(ContextState())], TypeForm[ContextState]))
    static_assert(is_equivalent_to(TypeOf[Given(NonPydanticType(1))], TypeForm[NonPydanticType]))

    # ... and that is what `DepOf` is, a marker held as a value
    static_assert(is_equivalent_to(TypeOf[Given(value)], DepOf[int]))


async def _resolve_a_constant(value: int) -> None:
    # resolving it gives that back
    static_assert(is_equivalent_to(TypeOf[await resolve(Given(value))], int))
    static_assert(is_equivalent_to(TypeOf[await resolve(Given(ContextState()))], ContextState))


def _negatives() -> None:
    Given()  # type: ignore[ty:missing-argument]
    Given(value=1)  # type: ignore[ty:positional-only-parameter-as-kwarg]
