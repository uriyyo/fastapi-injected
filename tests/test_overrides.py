from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import pytest

from fastapi_injected import Dep, ValueOverride, push_inject_scope, push_overrides, resolve
from fastapi_injected.overrides import (
    NonFreshScopeError,
    OverridesProvider,
    create_fallback_override_provider,
)

from .deps import Child, Container, ContextState, ctx_dep

pytestmark = pytest.mark.asyncio


@dataclass
class Provider:
    dependency_overrides: Mapping[Any, Any] = field(default_factory=dict)


def _child_factory(child: Child) -> Any:
    async def _factory() -> Child:
        return child

    return _factory


async def test_push_overrides():
    child = Child()

    with push_overrides({Child: ValueOverride(child)}):
        container = await resolve(Container)

    assert container.child is child


async def test_push_overrides_provider():
    child = Child()
    provider = Provider({Child: _child_factory(child)})

    with push_overrides(provider=provider):
        container = await resolve(Container)

    assert container.child is child


async def test_push_overrides_without_anything():
    with push_overrides():
        container = await resolve(Container)

    assert isinstance(container.child, Child)


async def test_push_overrides_take_precedence_over_provider():
    from_overrides, from_provider = Child(), Child()
    provider = Provider({Child: _child_factory(from_provider)})

    with push_overrides({Child: ValueOverride(from_overrides)}, provider=provider):
        container = await resolve(Container)

    assert container.child is from_overrides


async def test_push_overrides_fallback_to_outer_provider():
    child, ctx = Child(), ContextState()

    with push_overrides({Child: ValueOverride(child)}):
        with push_overrides({ctx_dep: ValueOverride(ctx)}, require_fresh_scope=False):
            container = await resolve(Container)

            # `ctx` comes from the inner overrides, `child` falls back to the outer ones
            assert container.ctx is ctx
            assert container.child is child

        container = await resolve(Container)

        assert container.ctx is not ctx
        assert container.child is child


async def test_push_overrides_provider_fallback_to_outer_provider():
    outer = Child()
    provider = Provider()

    with push_overrides({Child: ValueOverride(outer)}), push_overrides(provider=provider, require_fresh_scope=False):
        container = await resolve(Container)

    assert container.child is outer


async def test_push_overrides_requires_fresh_scope():
    async with push_inject_scope():
        await resolve(Container)

        with pytest.raises(NonFreshScopeError), push_overrides({Child: ValueOverride(Child())}):
            pass  # pragma: no cover


async def test_create_fallback_override_provider():
    child = Child()
    provider = create_fallback_override_provider(overrides={Dep[Child]: ValueOverride(child)})

    assert isinstance(provider, OverridesProvider)
    assert list(provider.dependency_overrides) == [Child]
