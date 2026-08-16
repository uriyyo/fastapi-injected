from collections.abc import Iterator
from typing import Any

from fastapi_injected import Dep, Given, MakeInjected, resolve
from fastapi_injected.types import DepOf

from .deps import (
    Child,
    ContextState,
    TypeOf,
    is_equivalent_to,
    is_subtype_of,
    static_assert,
)


class Check(MakeInjected):
    state: DepOf[ContextState]
    child: DepOf[Child]
    loud: bool = False

    async def __call__(self, state: ContextState, child: Child) -> bool:
        return state.closed and self.loud and child is not None


static_assert(is_subtype_of(Check, MakeInjected))


async def _fields_and_call() -> None:
    check = Check(state=Given(ContextState()), child=Dep[Child])

    static_assert(is_equivalent_to(TypeOf[check], Check))
    static_assert(is_equivalent_to(TypeOf[check.loud], bool))

    # a field holds the marker itself, which is what tells it from a parameter that
    # receives what the marker resolves to
    static_assert(is_equivalent_to(TypeOf[check.state], DepOf[ContextState]))

    # ... and resolving the whole thing is resolving its call
    static_assert(is_equivalent_to(TypeOf[await resolve(check)], bool))


def _deps(check: Check) -> None:
    static_assert(is_equivalent_to(TypeOf[check.__deps__()], Iterator[DepOf[Any]]))


def _negatives() -> None:
    Check()  # type: ignore[ty:missing-argument]
    Check(state=Given(ContextState()))  # type: ignore[ty:missing-argument]
    Check(state=Given(ContextState()), child=Dep[Child], unknown=1)  # type: ignore[ty:unknown-argument]
    Check(state=Given(ContextState()), child=Dep[Child], loud="yes")  # type: ignore[ty:invalid-argument-type]
