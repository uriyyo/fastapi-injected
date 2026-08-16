import asyncio
from dataclasses import dataclass
from typing import Annotated

import pytest
from fastapi import Depends

from fastapi_injected import Dep, Injected, inject, push_inject_scope, resolve

pytestmark = pytest.mark.asyncio


@dataclass
class Session:
    pass


async def get_session() -> Session:
    await asyncio.sleep(0.01)
    return Session()


SessionDep = Annotated[Session, Depends(get_session)]


@dataclass
class Repository:
    session: SessionDep


async def test_concurrent_resolve_reuses_cache():
    async with push_inject_scope():
        sessions = await asyncio.gather(*[resolve(SessionDep) for _ in range(4)])

    assert len({id(session) for session in sessions}) == 1


async def test_concurrent_inject_reuses_cache():
    @inject
    async def func(*, repo: Dep[Repository] = Injected) -> Session:
        return repo.session

    async with push_inject_scope():
        sessions = await asyncio.gather(*[func() for _ in range(4)])

    assert len({id(session) for session in sessions}) == 1


async def test_concurrent_resolve_without_scope_is_not_shared():
    sessions = await asyncio.gather(*[resolve(SessionDep) for _ in range(4)])

    assert len({id(session) for session in sessions}) == 4


async def nested_resolve_dep() -> Session:
    # a dependency is free to resolve more dependencies while the scope is locked for it
    return await resolve(SessionDep)


async def spawning_dep() -> Session:
    # resolving from a task the dependency spawned itself must not block on the scope
    [session] = await asyncio.gather(resolve(SessionDep))
    return session


async def test_nested_resolve_in_spawned_task_does_not_deadlock():
    async with push_inject_scope():
        async with asyncio.timeout(5):
            session = await resolve(spawning_dep)

        assert session is await resolve(SessionDep)


async def test_nested_resolve_does_not_deadlock():
    async with push_inject_scope():
        async with asyncio.timeout(5):
            session = await resolve(nested_resolve_dep)

        assert session is await resolve(SessionDep)
