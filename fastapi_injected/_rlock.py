import asyncio
from dataclasses import dataclass, field
from types import TracebackType
from typing import Any, Self


@dataclass
class RLock:
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)
    _owner: asyncio.Task[Any] | None = field(default=None, repr=False)
    _depth: int = field(default=0, repr=False)

    def locked(self) -> bool:
        return self._lock.locked()

    async def acquire(self) -> None:
        task = asyncio.current_task()

        if task is not None and self._owner is task:
            self._depth += 1
            return

        await self._lock.acquire()

        self._owner = task
        self._depth = 1

    def release(self) -> None:
        if not self._depth:
            raise RuntimeError("Lock is not acquired")

        self._depth -= 1

        if not self._depth:
            self._owner = None
            self._lock.release()

    async def __aenter__(self) -> Self:
        await self.acquire()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
        /,
    ) -> None:
        self.release()


__all__ = [
    "RLock",
]
