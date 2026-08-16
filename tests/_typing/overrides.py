from collections.abc import AsyncIterator

from fastapi_injected import Dep, DepFactory, FactoryOverride, ValueOverride, push_overrides
from fastapi_injected.overrides import NonFreshScopeError, OverridesProvider

from .deps import (
    Child,
    Container,
    ContextState,
    TypeOf,
    ctx_dep,
    get_value,
    is_equivalent_to,
    is_subtype_of,
    static_assert,
)

static_assert(is_subtype_of(NonFreshScopeError, Exception))

# the wrappers are generic in what they produce
static_assert(is_equivalent_to(TypeOf[ValueOverride(ContextState())], ValueOverride[ContextState]))
static_assert(is_equivalent_to(TypeOf[ValueOverride(1)], ValueOverride[int]))
# a generator factory is not unwrapped by the type checker, it keeps the type it declares
static_assert(is_equivalent_to(TypeOf[FactoryOverride(ctx_dep)], FactoryOverride[[], AsyncIterator[ContextState]]))
static_assert(is_equivalent_to(TypeOf[FactoryOverride(get_value)], FactoryOverride[[], int]))


def _overrides() -> None:
    # keys are the dependency itself or any annotation of it, values anything
    with push_overrides(
        {
            Child: Child(),
            Container: ValueOverride(Container(Child(), ContextState())),
            Dep[ContextState]: FactoryOverride(ctx_dep),
            DepFactory[ContextState, ctx_dep]: ContextState(),
        },
    ):
        pass

    # both the map and the provider are optional
    with push_overrides():
        pass

    with push_overrides(provider=OverridesProvider({Child: Child()}), require_fresh_scope=False):
        pass


def _negatives() -> None:
    push_overrides(require_fresh_scope="yes")  # type: ignore[ty:invalid-argument-type]
    push_overrides(provider=object())  # type: ignore[ty:invalid-argument-type]
    push_overrides({}, {})  # type: ignore[ty:too-many-positional-arguments]

    # the wrappers keep track of what they hold
    _: ValueOverride[int] = ValueOverride(ContextState())  # type: ignore[ty:invalid-assignment]
    __: FactoryOverride[[], str] = FactoryOverride(get_value)  # type: ignore[ty:invalid-assignment]
