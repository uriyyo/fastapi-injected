from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import pytest

from fastapi_injected import ValueOverride, push_inject_scope, push_overrides, resolve

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
        with push_overrides({ctx_dep: ValueOverride(ctx)}):
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

    with push_overrides({Child: ValueOverride(outer)}), push_overrides(provider=provider):
        container = await resolve(Container)

    assert container.child is outer


async def test_push_overrides_inside_a_used_scope():
    async with push_inject_scope():
        before = await resolve(Container)

        child = Child()
        with push_overrides({Child: ValueOverride(child)}):
            # the override applies even though the scope has already resolved the graph
            overridden = await resolve(Container)

            assert overridden.child is child
            assert overridden is not before

        # ... and what it produced does not outlive the block
        assert (await resolve(Container)) is before


async def test_push_overrides_reuses_what_it_does_not_override():
    async with push_inject_scope():
        before = await resolve(Container)

        with push_overrides({Child: ValueOverride(Child())}):
            # `ctx` does not depend on the overridden dependency, so it is not rebuilt
            assert (await resolve(ctx_dep)) is before.ctx


async def test_push_overrides_caches_inside_the_block():
    async with push_inject_scope():
        with push_overrides({Child: ValueOverride(Child())}):
            first = await resolve(Container)
            second = await resolve(Container)

            assert first is second
