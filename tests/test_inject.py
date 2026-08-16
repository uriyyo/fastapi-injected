import inspect
from typing import Annotated

import pytest
from fastapi import Depends, Query, Request

from fastapi_injected import Arg, Dep, Injected, NotADependencyError, inject, push_inject_scope

from .deps import Child, Container, ContextState, NonPydanticType

pytestmark = pytest.mark.asyncio

type ChildDep = Annotated[Child, Depends(Child)]


async def test_inject():

    @inject
    async def func(
        *,
        bar: Dep[Container] = Injected,
    ) -> None:
        assert isinstance(bar, Container)
        assert isinstance(bar.child, Child)
        assert isinstance(bar.ctx, ContextState)

    await func()


async def test_inject_reuse_cache():
    @inject
    async def func(
        *,
        bar: Dep[Container] = Injected,
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
        bar: Dep[Container] = Injected,
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
        bar: Dep[Container] = Injected,
    ) -> int:
        assert isinstance(bar, Container)
        assert isinstance(bar.child, Child)
        assert isinstance(bar.ctx, ContextState)

        return a + b

    result = await func(1, 2)
    assert result == 3


async def test_inject_func_with_non_pydantic_arg():
    # an argument that is not a dependency is never shown to pydantic, so it needs no marker
    @inject
    async def func(
        a: NonPydanticType,
        *,
        b: NonPydanticType,
        bar: Dep[Container] = Injected,
    ) -> int:
        assert isinstance(bar, Container)

        return a.value + b.value

    result = await func(NonPydanticType(1), b=NonPydanticType(2))
    assert result == 3


async def test_arg_opts_a_dependency_out_of_the_graph():
    @inject
    async def func(
        child: Arg[Dep[Child]],
        *,
        bar: Dep[Container] = Injected,
    ) -> Child:
        assert isinstance(bar, Container)

        return child

    passed = Child()
    assert await func(passed) is passed


async def test_arg_leaves_the_parameter_in_the_public_signature():
    @inject
    async def func(
        child: Arg[Dep[Child]],
        *,
        bar: Dep[Container] = Injected,
    ) -> None:
        pass

    assert [*inspect.signature(func).parameters] == ["child"]


async def test_a_dependency_passed_as_a_default_is_injected():
    @inject
    async def func(child: Child = Depends(Child)) -> Child:  # noqa: B008 - the spelling under test
        return child

    assert isinstance(await func(), Child)


async def test_a_dependency_written_as_an_alias_is_injected():
    @inject
    async def func(child: ChildDep = Injected) -> Child:
        return child

    assert isinstance(await func(), Child)


async def test_fastapi_parameters_stay_caller_supplied():
    # `@inject` resolves dependencies, not request parameters - those are still the caller's
    @inject
    async def func(
        request: Request,
        page: Annotated[int, Query()],
        *,
        bar: Dep[Container] = Injected,
    ) -> str:
        assert isinstance(bar, Container)

        return f"{request}:{page}"

    assert [*inspect.signature(func).parameters] == ["request", "page"]
    assert await func("request", 1) == "request:1"


async def test_injected_default_without_a_dependency_is_a_mistake():
    with pytest.raises(NotADependencyError, match="'child'"):

        @inject
        async def func(
            *,
            child: Child = Injected,
        ) -> None:
            pass


async def test_inject_teardown():
    @inject
    async def func(
        *,
        bar: Dep[Container] = Injected,
    ) -> ContextState:
        assert not bar.ctx.closed
        return bar.ctx

    ctx = await func()
    assert ctx.closed


async def test_inject_teardown_in_scope():
    @inject
    async def func(
        *,
        bar: Dep[Container] = Injected,
    ) -> ContextState:
        assert not bar.ctx.closed
        return bar.ctx

    async with push_inject_scope():
        ctx = await func()
        assert not ctx.closed

        ctx = await func()
        assert not ctx.closed

    assert ctx.closed
