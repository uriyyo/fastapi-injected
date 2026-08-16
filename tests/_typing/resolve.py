from collections.abc import Iterator

from fastapi import Depends, params

from fastapi_injected import Dep, DepFactory, resolve

from .deps import (
    Container,
    ContextState,
    NonPydanticType,
    TypeOf,
    coro_ctx_dep,
    ctx_dep,
    get_value,
    is_equivalent_to,
    static_assert,
    sync_ctx_dep,
)


async def _resolve_a_type() -> None:
    # a type resolves to an instance of itself
    static_assert(is_equivalent_to(TypeOf[await resolve(Container)], Container))
    static_assert(is_equivalent_to(TypeOf[await resolve(NonPydanticType)], NonPydanticType))

    # ... and so does an annotation, since both markers are the type itself
    static_assert(is_equivalent_to(TypeOf[await resolve(Dep[Container])], Container))
    static_assert(is_equivalent_to(TypeOf[await resolve(DepFactory[ContextState, ctx_dep])], ContextState))


async def _resolve_a_factory() -> None:
    # a factory resolves to what it produces, whatever shape it has
    static_assert(is_equivalent_to(TypeOf[await resolve(get_value)], int))
    static_assert(is_equivalent_to(TypeOf[await resolve(coro_ctx_dep)], ContextState))
    static_assert(is_equivalent_to(TypeOf[await resolve(sync_ctx_dep)], ContextState))
    static_assert(is_equivalent_to(TypeOf[await resolve(ctx_dep)], ContextState))


class DependsHook:
    def __call__(self) -> ContextState:
        return ContextState()

    def __get_depends__(self) -> params.Depends:
        return Depends(ContextState)


async def _resolve_a_depends_hook() -> None:
    # an object that brings its own `Depends` resolves to what it produces too
    static_assert(is_equivalent_to(TypeOf[await resolve(DependsHook())], ContextState))


async def _resolve_options() -> None:
    static_assert(is_equivalent_to(TypeOf[await resolve(Container, new_scope=True)], Container))


async def _negatives() -> None:
    await resolve(Container, True)  # type: ignore[ty:no-matching-overload]
    await resolve(Container, new_scope="yes")  # type: ignore[ty:no-matching-overload]
    await resolve()  # type: ignore[ty:no-matching-overload]

    # what `resolve` returns is the dependency, not the marker
    _ = (await resolve(Container)).unknown  # type: ignore[ty:unresolved-attribute]


class CallableDep:
    def __call__(self) -> Iterator[ContextState]:
        yield ContextState()


def list_dep() -> list[int]:
    return [1]


def dict_dep() -> dict[str, int]:
    return {}


def str_dep() -> str:
    return ""


async def _resolve_shapes() -> None:
    # a generator behind `__call__` is a generator dependency to fastapi as well
    static_assert(is_equivalent_to(TypeOf[await resolve(CallableDep())], ContextState))

    # a dependency returning a collection produces the collection, not what is inside it,
    # which is why `Iterable` is not one of the shapes a dependency can declare through
    static_assert(is_equivalent_to(TypeOf[await resolve(list_dep)], list[int]))
    static_assert(is_equivalent_to(TypeOf[await resolve(dict_dep)], dict[str, int]))
    static_assert(is_equivalent_to(TypeOf[await resolve(str_dep)], str))
