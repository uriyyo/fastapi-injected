from fastapi_injected import Arg, Dep, Injected, inject

from .deps import (
    Child,
    Container,
    NonPydanticType,
    TypeOf,
    is_equivalent_to,
    static_assert,
)

# like `Dep`, `Arg` is transparent - what it wraps is what the parameter is typed as
static_assert(is_equivalent_to(Arg[NonPydanticType], NonPydanticType))
static_assert(is_equivalent_to(Arg[int], int))
static_assert(is_equivalent_to(Arg[Container], Container))

# wrapping a dependency keeps its type too - only where the value comes from changes
static_assert(is_equivalent_to(Arg[Dep[Child]], Child))


@inject
async def handler(
    a: NonPydanticType,
    *,
    b: NonPydanticType,
    container: Dep[Container] = Injected,
) -> int:
    # a parameter that is not a dependency needs no marker and keeps its own type
    static_assert(is_equivalent_to(TypeOf[a], NonPydanticType))
    static_assert(is_equivalent_to(TypeOf[b], NonPydanticType))
    static_assert(is_equivalent_to(TypeOf[container], Container))

    return a.value + b.value


@inject
async def opted_out(
    child: Arg[Dep[Child]],
    *,
    container: Dep[Container] = Injected,
) -> Child:
    # `Arg` takes it out of the graph, so it arrives from the caller with the type it wraps
    static_assert(is_equivalent_to(TypeOf[child], Child))
    static_assert(is_equivalent_to(TypeOf[container], Container))

    return child


async def _calls() -> None:
    # ... and at the call site they are plain arguments, still checked
    static_assert(is_equivalent_to(TypeOf[await handler(NonPydanticType(1), b=NonPydanticType(2))], int))
    static_assert(is_equivalent_to(TypeOf[await opted_out(Child())], Child))


async def _negatives() -> None:
    await handler(1, b=NonPydanticType(2))  # type: ignore[ty:invalid-argument-type]
    await handler(NonPydanticType(1))  # type: ignore[ty:missing-argument]

    # an opted-out dependency is not resolved for you, so it stays required
    await opted_out()  # type: ignore[ty:missing-argument]
