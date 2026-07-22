from typing import Any

import pytest
from pydantic_ai import Agent, RunContext
from pydantic_ai.models.test import TestModel

from fastapi_injected import Dep, Injected, inject
from tests.deps import Container

pytestmark = pytest.mark.asyncio

agent = Agent()


@agent.tool
@inject
async def tool1(
    ctx: RunContext[Any],
    a: int,
    *,
    container: Dep[Container] = Injected,
) -> int:
    assert isinstance(container, Container)

    return a * 2


@agent.tool_plain
@inject
async def tool2(
    a: int,
    *,
    container: Dep[Container] = Injected,
) -> int:
    assert isinstance(container, Container)
    return a * 2


async def test_agent_integration():
    with agent.override(model=TestModel()):
        await agent.run("test")
