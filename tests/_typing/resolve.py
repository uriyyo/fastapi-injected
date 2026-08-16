from collections.abc import AsyncIterator

from fastapi_injected import Dep, DepFactory, resolve

from .deps import (
    Container,
    ContextState,
    NonPydanticType,
    TypeOf,
    ctx_dep,
    get_value,
    is_equivalent_to,
    static_assert,
)


async def _resolve_a_type() -> None:
    # a type resolves to an instance of itself
    static_assert(is_equivalent_to(TypeOf[await resolve(Container)], Container))
    static_assert(is_equivalent_to(TypeOf[await resolve(NonPydanticType)], NonPydanticType))

    # ... and so does an annotation, since both markers are the type itself
    static_assert(is_equivalent_to(TypeOf[await resolve(Dep[Container])], Container))
    static_assert(is_equivalent_to(TypeOf[await resolve(DepFactory[ContextState, ctx_dep])], ContextState))


async def _resolve_a_factory() -> None:
    # a factory resolves to what it produces
    static_assert(is_equivalent_to(TypeOf[await resolve(get_value)], int))

    # for a generator factory both `DepReturn` members match, so the result is widened -
    # what is resolved at runtime is always the yielded value
    static_assert(is_equivalent_to(TypeOf[await resolve(ctx_dep)], ContextState | AsyncIterator[ContextState]))


async def _resolve_options() -> None:
    static_assert(is_equivalent_to(TypeOf[await resolve(Container, new_scope=True)], Container))


async def _negatives() -> None:
    await resolve(Container, True)  # type: ignore[ty:no-matching-overload]
    await resolve(Container, new_scope="yes")  # type: ignore[ty:no-matching-overload]
    await resolve()  # type: ignore[ty:no-matching-overload]

    # what `resolve` returns is the dependency, not the marker
    _ = (await resolve(Container)).unknown  # type: ignore[ty:unresolved-attribute]
