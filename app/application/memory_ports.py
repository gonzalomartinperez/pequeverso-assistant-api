"""Visitor memory port and its closed fact schema (PVA-M4-X, ADR-0021).

Memory personalises tone, length and example order only: it never changes a commercial fact,
a price or a corpus answer, and it never enters the answer-rule allowlists. The feature ships
disabled (flag `memory`, DR-07 legal review).
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, NewType, Protocol

if TYPE_CHECKING:
    from datetime import datetime

# The server-issued visitor key from the opt-in cookie, never a request-body or model value.
# Adapters that persist facts key rows by an HMAC of it (assistant-experience.md section 6.3).
VisitorKey = NewType("VisitorKey", str)

# Each fact expires a fixed period after its own last write; reads never extend it.
MEMORY_TTL = timedelta(days=60)

# Closed schema: an enumerated key with enumerated values. Free text, names, contact data, precise
# ages and anything outside these sets are never stored. `child_age_band` is coarse on purpose and
# stays disabled until the DR-07 review covers it.
MEMORY_FACTS: dict[str, frozenset[str]] = {
    "verbosity": frozenset({"short", "normal"}),
    "audience_role": frozenset({"parent", "educator", "gift_buyer"}),
    "child_age_band": frozenset({"2-3", "4-5", "6-7"}),
}


def allowed_fact(key: str, value: str) -> bool:
    """Return whether `key` and `value` belong to the closed fact schema."""
    return value in MEMORY_FACTS.get(key, frozenset())


class MemoryStore(Protocol):
    """Closed-schema visitor memory; every method is scoped to one visitor key."""

    async def write(self, visitor_key: VisitorKey, key: str, value: str, *, consent: bool) -> bool:
        """Store one enumerated fact; return False when refused (no consent or outside the schema)."""
        ...

    async def read(self, visitor_key: VisitorKey, *, consent: bool) -> dict[str, str]:
        """Return this visitor's live facts; empty without consent or after each fact's TTL."""
        ...

    async def forget(self, visitor_key: VisitorKey) -> int:
        """Erase everything keyed by the visitor and return the number of live facts removed."""
        ...

    async def purge_expired(self, now: datetime) -> int:
        """Delete facts past their TTL for every visitor (the retention job); return the count."""
        ...

    async def rows_for(self, visitor_key: VisitorKey) -> int:
        """Return every row still keyed by the visitor, for the forget-completeness audit."""
        ...
