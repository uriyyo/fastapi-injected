from typing import Any

from fastapi_injected import Dep, DepFactory, is_dep, unwrap_dep_dependency, unwrap_dep_tp

from .deps import (
    Container,
    ContextState,
    TypeOf,
    ctx_dep,
    is_equivalent_to,
    static_assert,
)

# the inspection helpers work on annotations, so they take and give back untyped values
static_assert(is_equivalent_to(TypeOf[is_dep(Dep[Container])], bool))
static_assert(is_equivalent_to(TypeOf[is_dep(object())], bool))
static_assert(is_equivalent_to(TypeOf[unwrap_dep_tp(Dep[Container])], Any))
static_assert(is_equivalent_to(TypeOf[unwrap_dep_dependency(DepFactory[ContextState, ctx_dep])], Any))


def _negatives() -> None:
    is_dep()  # type: ignore[ty:missing-argument]
    unwrap_dep_tp(Dep[Container], Container)  # type: ignore[ty:too-many-positional-arguments]
    unwrap_dep_dependency(obj=Dep[Container])  # type: ignore[ty:positional-only-parameter-as-kwarg]
