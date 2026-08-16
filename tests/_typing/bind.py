import inspect
from collections.abc import Sequence
from typing import Any

from fastapi_injected import DepFactory, Given, bind_deps, resolve, signature_with_deps
from fastapi_injected._bind import UnboundDepArgsError, dep_arg_name, remap_dep_args, take_dep_args
from fastapi_injected.types import DepOf

from .deps import (
    ContextState,
    TypeOf,
    ctx_dep,
    is_equivalent_to,
    is_subtype_of,
    static_assert,
)

static_assert(is_subtype_of(UnboundDepArgsError, ValueError))


async def _describe(state: ContextState, value: int) -> str:
    return f"{state.closed}{value}"


async def _greet(state: ContextState, greeting: str = "hello") -> str:
    return f"{greeting}{state.closed}"


async def _six(one: int, two: int, three: int, four: int, five: int, six: int) -> str:  # noqa: PLR0913, PLR0917
    return f"{one}{two}{three}{four}{five}{six}"


def _sync_describe(state: ContextState) -> str:
    return f"{state.closed}"  # pragma: no cover


async def _bound() -> None:
    bound = bind_deps(_describe, Given(ContextState()), Given(1))

    # a bound function produces what it produced before binding, and is a dependency
    static_assert(is_equivalent_to(TypeOf[await resolve(bound)], str))


async def _what_is_left_to_bind() -> None:
    # binding takes the leading parameters away, and the rest stay what they were
    nothing_bound = bind_deps(_greet)
    static_assert(is_equivalent_to(TypeOf[await nothing_bound(ContextState(), "hi")], str))

    one_bound = bind_deps(_greet, Given(ContextState()))
    static_assert(is_equivalent_to(TypeOf[await one_bound("hi")], str))
    static_assert(is_equivalent_to(TypeOf[await one_bound()], str))

    both_bound = bind_deps(_greet, Given(ContextState()), Given("hi"))
    static_assert(is_equivalent_to(TypeOf[await both_bound()], str))

    # a callable binds a parameter the same way, and leaves the rest as they were
    static_assert(is_equivalent_to(TypeOf[await bind_deps(_greet, ctx_dep)("hi")], str))

    # what it is bound to is any marker, however it was written - or the callable itself
    bind_deps(_describe, Given(ContextState()), DepFactory[ContextState, ctx_dep])
    bind_deps(_describe, ctx_dep, ContextState)


def _markers_can_be_unpacked(deps: Sequence[DepOf[Any]]) -> None:
    bind_deps(_describe, *deps)


async def _pieces() -> None:
    static_assert(is_equivalent_to(TypeOf[signature_with_deps(_describe)], inspect.Signature))
    static_assert(is_equivalent_to(TypeOf[dep_arg_name(0)], str))
    static_assert(is_equivalent_to(TypeOf[take_dep_args({})], list[Any]))

    # remapping only changes where the arguments come from, not what the function is
    remapped = remap_dep_args(_describe)

    static_assert(is_equivalent_to(TypeOf[await remapped(ContextState(), 1)], str))


async def _more_than_the_overloads_cover() -> None:
    # the last one that peels a parameter off
    five_bound = bind_deps(_six, Given(1), Given(2), Given(3), Given(4), Given(5))
    static_assert(is_equivalent_to(TypeOf[await five_bound(6)], str))

    # past that the parameters are left open, and what it produces is still known
    six_bound = bind_deps(_six, Given(1), Given(2), Given(3), Given(4), Given(5), Given(6))
    static_assert(is_equivalent_to(TypeOf[await six_bound()], str))


async def _negatives_on_what_is_left() -> None:
    one_bound = bind_deps(_greet, Given(ContextState()))

    await one_bound(ContextState())  # type: ignore[ty:invalid-argument-type]
    await one_bound("hi", "extra")  # type: ignore[ty:too-many-positional-arguments]
    await bind_deps(_greet, Given(ContextState()), Given("hi"))("hi")  # type: ignore[ty:too-many-positional-arguments]


def _negatives() -> None:
    bind_deps()  # type: ignore[ty:no-matching-overload]
    bind_deps(_describe, 42)  # type: ignore[ty:invalid-type-form]

    # the call is awaited, so it has to be one that can be
    bind_deps(_sync_describe)  # type: ignore[ty:no-matching-overload]
    remap_dep_args(_sync_describe)  # type: ignore[ty:invalid-argument-type]

    dep_arg_name("0")  # type: ignore[ty:invalid-argument-type]
