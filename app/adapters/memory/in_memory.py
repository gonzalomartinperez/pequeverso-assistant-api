"""Process-local visitor memory for tests and the fixture profile (PVA-M4-X).

Each visitor has its own dictionary: no shared state, no cache that outlives `forget`, a fixed TTL
measured from the write. A PostgreSQL adapter with the same contract follows when the `memory`
flag can be enabled (DR-07).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.application.memory_ports import MEMORY_TTL, allowed_fact

if TYPE_CHECKING:
    from datetime import datetime

    from app.application.ports import Clock


class InMemoryMemoryStore:
    """Isolated per-visitor facts with consent, closed schema and fixed expiry."""

    def __init__(self, clock: Clock) -> None:
        self._clock = clock
        self._facts: dict[str, dict[str, tuple[str, datetime]]] = {}

    def write(self, visitor_key: str, key: str, value: str, *, consent: bool) -> bool:
        """Store one enumerated fact when the visitor consented; refuse anything else."""
        if not consent or not allowed_fact(key, value):
            return False
        self._facts.setdefault(visitor_key, {})[key] = (value, self._clock.now())
        return True

    def read(self, visitor_key: str, *, consent: bool) -> dict[str, str]:
        """Return the visitor's facts written within the TTL; nothing without consent."""
        if not consent:
            return {}
        now = self._clock.now()
        return {
            key: value
            for key, (value, written_at) in self._facts.get(visitor_key, {}).items()
            if now - written_at < MEMORY_TTL
        }

    def forget(self, visitor_key: str) -> int:
        """Erase the visitor's facts and return how many live facts were removed."""
        live = len(self.read(visitor_key, consent=True))
        self._facts.pop(visitor_key, None)
        return live

    def rows_for(self, visitor_key: str) -> int:
        """Return the stored rows still keyed by the visitor, expired ones included."""
        return len(self._facts.get(visitor_key, {}))
