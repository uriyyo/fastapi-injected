from dataclasses import field

from fastapi_injected import MakeDataclass

from .deps import (
    ContextState,
    TypeOf,
    is_equivalent_to,
    static_assert,
)


class Point(MakeDataclass):
    x: int
    y: int = 0


class KeywordOnly(MakeDataclass, frozen=True, kw_only=True):
    state: ContextState = field(default_factory=ContextState)


# subclasses are dataclasses to a type checker too, so their `__init__` is known
static_assert(is_equivalent_to(TypeOf[Point(1)], Point))
static_assert(is_equivalent_to(TypeOf[Point(1, 2)], Point))
static_assert(is_equivalent_to(TypeOf[Point(x=1, y=2)], Point))
static_assert(is_equivalent_to(TypeOf[KeywordOnly()], KeywordOnly))
static_assert(is_equivalent_to(TypeOf[KeywordOnly(state=ContextState())], KeywordOnly))

# ... and they always have a hash, whatever they are built from
static_assert(is_equivalent_to(TypeOf[hash(Point(1))], int))


def _negatives() -> None:
    Point()  # type: ignore[ty:missing-argument]
    Point("1")  # type: ignore[ty:invalid-argument-type]
    Point(1, 2, 3)  # type: ignore[ty:too-many-positional-arguments]
    KeywordOnly(ContextState())  # type: ignore[ty:too-many-positional-arguments]
