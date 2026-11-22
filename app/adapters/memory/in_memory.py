"""Process-local visitor memory for tests and the fixture profile (PVA-M4-X, ADR-0021).

Each visitor has its own dictionary: no shared state, no cache that outlives `forget`, and a fixed
TTL measured from each fact's own write. A PostgreSQL adapter with the same contract (and HMAC row
keys) follows when the `memory` flag can be enabled (DR-07).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.application.memory_ports import MEMORY_TTL, allowed_fact

if TYPE_CHECKING:
    from datetime import datetime

    from app.application.memory_ports import VisitorKey
    from app.application.ports import Clock


class InMemoryMemoryStore:
    """Isolated per-visitor facts with consent, closed schema and fixed per-fact expiry."""

    def __init__(self, clock: Clock) -> None:
        self._clock = clock
        self._facts: dict[str, dict[str, tuple[str, datetime]]] = {}

    async def write(self, visitor_key: VisitorKey, key: str, value: str, *, consent: bool) -> bool:
        """Store one enumerated fact when the visitor consented; refuse anything else."""
        if not visitor_key or not consent or not allowed_fact(key, value):
            return False
        self._facts.setdefault(visitor_key, {})[key] = (value, self._clock.now())
        return True

    async def read(self, visitor_key: VisitorKey, *, consent: bool) -> dict[str, str]:
        """Return the visitor's facts written within the TTL; nothing without consent."""
        if not consent:
            return {}
        return self._live(visitor_key, self._clock.now())

    async def forget(self, visitor_key: VisitorKey) -> int:
        """Erase the visitor's facts and return how many live facts were removed."""
        live = len(self._live(visitor_key, self._clock.now()))
        self._facts.pop(visitor_key, None)
        return live

    async def purge_expired(self, now: datetime) -> int:
        """Delete every fact past its TTL and drop visitors left without facts."""
        removed = 0
        for visitor_key in list(self._facts):
            facts = self._facts[visitor_key]
            expired = [
                key for key, (_, written_at) in facts.items() if now - written_at >= MEMORY_TTL
            ]
            for key in expired:
                del facts[key]
            removed += len(expired)
            if not facts:
                del self._facts[visitor_key]
        return removed

    async def rows_for(self, visitor_key: VisitorKey) -> int:
        """Return the stored rows still keyed by the visitor, expired ones included."""
        return len(self._facts.get(visitor_key, {}))

    def _live(self, visitor_key: str, now: datetime) -> dict[str, str]:
        return {
            key: value
            for key, (value, written_at) in self._facts.get(visitor_key, {}).items()
            if now - written_at < MEMORY_TTL
        }
