import pytest

from fastapi_injected import Dep, Inejected, inject, push_inject_scope

from .deps import Child, Container, ContextState

pytestmark = pytest.mark.asyncio


async def test_inject():

    @inject
    async def func(
        *,
        bar: Dep[Container] = Inejected,
    ) -> None:
        assert isinstance(bar, Container)
        assert isinstance(bar.child, Child)
        assert isinstance(bar.ctx, ContextState)

    await func()


async def test_inject_reuse_cache():
    @inject
    async def func(
        *,
        bar: Dep[Container] = Inejected,
    ) -> Container:
        return bar

    async with push_inject_scope():
        b1 = await func()
        b2 = await func()

        assert b1 is b2


async def test_inject_new_scope_use_different_cache():
    @inject(new_scope=True)
    async def func(
        *,
        bar: Dep[Container] = Inejected,
    ) -> Container:
        return bar

    async with push_inject_scope():
        b1 = await func()
        b2 = await func()

        assert b1 is not b2


async def test_inject_func_with_args():
    @inject
    async def func(
        a: int,
        b: int,
        *,
        bar: Dep[Container] = Inejected,
    ) -> int:
        assert isinstance(bar, Container)
        assert isinstance(bar.child, Child)
        assert isinstance(bar.ctx, ContextState)

        return a + b

    result = await func(1, 2)
    assert result == 3


async def test_inject_teardown():
    @inject
    async def func(
        *,
        bar: Dep[Container] = Inejected,
    ) -> ContextState:
        assert not bar.ctx.closed
        return bar.ctx

    ctx = await func()
    assert ctx.closed


async def test_inject_teardown_in_scope():
    @inject
    async def func(
        *,
        bar: Dep[Container] = Inejected,
    ) -> ContextState:
        assert not bar.ctx.closed
        return bar.ctx

    async with push_inject_scope():
        ctx = await func()
        assert not ctx.closed

        ctx = await func()
        assert not ctx.closed

    assert ctx.closed
