from fastapi_injected import Dep, DepFactory, FactoryOverride, ValueOverride, push_overrides
from fastapi_injected.overrides import OverridesProvider
from fastapi_injected.scope import InjectScope

from .deps import (
    Child,
    Container,
    ContextState,
    TypeOf,
    coro_ctx_dep,
    ctx_dep,
    get_value,
    is_equivalent_to,
    static_assert,
    sync_ctx_dep,
)

# the wrappers are generic in what they produce
static_assert(is_equivalent_to(TypeOf[ValueOverride(ContextState())], ValueOverride[ContextState]))
static_assert(is_equivalent_to(TypeOf[ValueOverride(1)], ValueOverride[int]))
# a factory is typed by what it produces, whatever shape it returns it in
static_assert(is_equivalent_to(TypeOf[FactoryOverride(ctx_dep)], FactoryOverride[[], ContextState]))
static_assert(is_equivalent_to(TypeOf[FactoryOverride(coro_ctx_dep)], FactoryOverride[[], ContextState]))
static_assert(is_equivalent_to(TypeOf[FactoryOverride(sync_ctx_dep)], FactoryOverride[[], ContextState]))
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

    with push_overrides(provider=OverridesProvider({Child: Child()})):
        pass

    # every override block is a scope of its own
    with push_overrides() as scope:
        static_assert(is_equivalent_to(TypeOf[scope], InjectScope))

        with scope.override({Child: Child()}) as nested:
            static_assert(is_equivalent_to(TypeOf[nested], InjectScope))


def _negatives() -> None:
    push_overrides(require_fresh_scope=True)  # type: ignore[ty:unknown-argument]
    push_overrides(provider=object())  # type: ignore[ty:invalid-argument-type]
    push_overrides({}, {})  # type: ignore[ty:too-many-positional-arguments]

    # the wrappers keep track of what they hold
    _: ValueOverride[int] = ValueOverride(ContextState())  # type: ignore[ty:invalid-assignment]
    __: FactoryOverride[[], str] = FactoryOverride(get_value)  # type: ignore[ty:invalid-assignment]
