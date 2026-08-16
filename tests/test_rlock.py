import asyncio

import pytest

from fastapi_injected._rlock import RLock

pytestmark = pytest.mark.asyncio


async def test_rlock_is_reentrant():
    lock = RLock()

    async with lock:
        async with lock:
            assert lock.locked()

        assert lock.locked()

    assert not lock.locked()


async def test_rlock_blocks_other_tasks():
    lock = RLock()
    order = []

    async def worker(name: str) -> None:
        async with lock:
            order.append(f"{name}-enter")
            await asyncio.sleep(0.01)
            order.append(f"{name}-exit")

    await asyncio.gather(worker("a"), worker("b"))

    assert order in (
        ["a-enter", "a-exit", "b-enter", "b-exit"],
        ["b-enter", "b-exit", "a-enter", "a-exit"],
    )


async def test_rlock_is_released_on_error():
    lock = RLock()

    with pytest.raises(ValueError, match="boom"):
        async with lock:
            raise ValueError("boom")

    assert not lock.locked()


async def test_rlock_inner_error_keeps_outer_lock():
    lock = RLock()

    async with lock:
        with pytest.raises(ValueError, match="boom"):
            async with lock:
                raise ValueError("boom")

        assert lock.locked()

    assert not lock.locked()


async def test_rlock_release_without_acquire():
    lock = RLock()

    with pytest.raises(RuntimeError, match="Lock is not acquired"):
        lock.release()


async def test_rlock_is_reentrant_in_spawned_tasks():
    lock = RLock()

    # a task spawned by the holder works on its behalf - it inherits the ownership
    async def worker() -> bool:
        async with lock:
            return lock.owned()

    async with lock:
        async with asyncio.timeout(1):
            assert await asyncio.create_task(worker())


async def test_rlock_blocks_tasks_created_outside_the_holder():
    lock = RLock()
    acquired = asyncio.Event()
    entered = asyncio.Event()

    async def worker() -> None:
        await acquired.wait()

        async with lock:
            entered.set()

    # the task copies the context before the lock is taken, so it does not own it
    task = asyncio.create_task(worker())
    await asyncio.sleep(0)

    async with lock:
        assert lock.owned()
        acquired.set()

        with pytest.raises(TimeoutError):
            async with asyncio.timeout(0.05):
                await entered.wait()

    await task
    assert entered.is_set()
