"""In-process registry of active runs, so a visitor can cancel their own run. The service runs as a
single process (docs/architecture.md); the persisted run state is the cross-restart record.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class _Handle:
    session_id: str
    cancel: asyncio.Event
    finished: asyncio.Event


@dataclass(slots=True)
class _SessionLock:
    lock: asyncio.Lock
    users: int = 0


class RunRegistry:
    def __init__(self) -> None:
        self._runs: dict[str, _Handle] = {}
        self._mutations: dict[str, _SessionLock] = {}
        self.closing = False

    @asynccontextmanager
    async def session_mutation(self, session_id: str) -> AsyncIterator[None]:
        """Serialize turn admission and deletion; release idle locks without retaining ids."""
        entry = self._mutations.setdefault(session_id, _SessionLock(asyncio.Lock()))
        entry.users += 1
        try:
            async with entry.lock:
                yield
        finally:
            entry.users -= 1
            if not entry.users:
                self._mutations.pop(session_id)

    def add(self, run_id: str, session_id: str) -> asyncio.Event:
        event = asyncio.Event()
        self._runs[run_id] = _Handle(session_id, event, asyncio.Event())
        return event

    def cancel(self, run_id: str, session_id: str) -> bool:
        handle = self._runs.get(run_id)
        if handle is None or handle.session_id != session_id:
            return False
        handle.cancel.set()
        return True

    def remove(self, run_id: str) -> None:
        handle = self._runs.pop(run_id, None)
        if handle is not None:
            handle.finished.set()

    async def cancel_session(self, session_id: str) -> None:
        handles = [handle for handle in self._runs.values() if handle.session_id == session_id]
        for handle in handles:
            handle.cancel.set()
        await asyncio.gather(*(handle.finished.wait() for handle in handles))

    def close(self) -> None:
        self.closing = True
        for handle in self._runs.values():
            handle.cancel.set()

    async def drain(self) -> None:
        await asyncio.gather(*(handle.finished.wait() for handle in tuple(self._runs.values())))

    def __len__(self) -> int:
        return len(self._runs)
