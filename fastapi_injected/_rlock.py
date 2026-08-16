import asyncio
from contextvars import ContextVar
from dataclasses import field
from types import TracebackType
from typing import Self

from ._dataclass import MakeDataclass

# ownership is tracked per context, not per task - a task spawned by the holder inherits
# a copy of its context, so work it does on the holder's behalf is not blocked by it
_held_locks: ContextVar[frozenset["RLock"]] = ContextVar(
    "_held_locks",
    default=frozenset(),
)


class RLock(MakeDataclass, eq=False):
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)
    _depth: int = field(default=0, repr=False)

    def locked(self) -> bool:
        return self._lock.locked()

    def owned(self) -> bool:
        return self in _held_locks.get()

    async def acquire(self) -> None:
        if self.owned():
            self._depth += 1
            return

        await self._lock.acquire()

        _held_locks.set(_held_locks.get() | {self})
        self._depth = 1

    def release(self) -> None:
        if not self._depth:
            raise RuntimeError("Lock is not acquired")

        self._depth -= 1

        if not self._depth:
            _held_locks.set(_held_locks.get() - {self})
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
