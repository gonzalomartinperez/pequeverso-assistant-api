"""In-process registry of active runs, so a visitor can cancel their own run. The service runs as a
single process (docs/architecture.md); the persisted run state is the cross-restart record.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class _Handle:
    session_id: str
    cancel: asyncio.Event


class RunRegistry:
    def __init__(self) -> None:
        self._runs: dict[str, _Handle] = {}

    def add(self, run_id: str, session_id: str) -> asyncio.Event:
        event = asyncio.Event()
        self._runs[run_id] = _Handle(session_id, event)
        return event

    def cancel(self, run_id: str, session_id: str) -> bool:
        handle = self._runs.get(run_id)
        if handle is None or handle.session_id != session_id:
            return False
        handle.cancel.set()
        return True

    def remove(self, run_id: str) -> None:
        self._runs.pop(run_id, None)

    def __len__(self) -> int:
        return len(self._runs)
