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


async def test_rlock_is_not_shared_between_tasks():
    lock = RLock()

    async def worker() -> bool:
        return lock.locked()

    async with lock:
        assert await asyncio.create_task(worker())

        with pytest.raises(TimeoutError):
            async with asyncio.timeout(0.05):
                await asyncio.create_task(_acquire(lock))


async def _acquire(lock: RLock) -> None:
    async with lock:
        pass
