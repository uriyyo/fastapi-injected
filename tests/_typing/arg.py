from fastapi_injected import Arg, Dep, Injected, inject

from .deps import (
    Container,
    NonPydanticType,
    TypeOf,
    is_equivalent_to,
    static_assert,
)

# like `Dep`, `Arg` is transparent - it only exists to keep pydantic away from the annotation
static_assert(is_equivalent_to(Arg[NonPydanticType], NonPydanticType))
static_assert(is_equivalent_to(Arg[int], int))
static_assert(is_equivalent_to(Arg[Container], Container))


@inject
async def handler(
    a: Arg[NonPydanticType],
    *,
    b: Arg[NonPydanticType],
    container: Dep[Container] = Injected,
) -> int:
    # inside the function the parameters keep the type they were wrapped around
    static_assert(is_equivalent_to(TypeOf[a], NonPydanticType))
    static_assert(is_equivalent_to(TypeOf[b], NonPydanticType))
    static_assert(is_equivalent_to(TypeOf[container], Container))

    return a.value + b.value


async def _calls() -> None:
    # ... and at the call site they are plain arguments, still checked
    static_assert(is_equivalent_to(TypeOf[await handler(NonPydanticType(1), b=NonPydanticType(2))], int))


async def _negatives() -> None:
    await handler(1, b=NonPydanticType(2))  # type: ignore[ty:invalid-argument-type]
    await handler(NonPydanticType(1))  # type: ignore[ty:missing-argument]
