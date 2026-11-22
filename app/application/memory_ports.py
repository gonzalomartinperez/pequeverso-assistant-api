"""Visitor memory port and its closed fact schema (PVA-M4-X, assistant-experience.md section 6).

Memory personalises tone, length and example order only: it never changes a commercial fact,
a price or a corpus answer, and it never enters the answer-rule allowlists. The feature ships
disabled (flag `memory`, DR-07 legal review), and `visitor_key` must come from the session only,
never from a request body or model output.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Protocol

# Fixed retention from the last write; reads never extend it (no refresh on read).
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
    """Closed-schema visitor memory keyed by the session's visitor key."""

    def write(self, visitor_key: str, key: str, value: str, *, consent: bool) -> bool:
        """Store one enumerated fact; return False when refused (no consent or outside the schema)."""
        ...

    def read(self, visitor_key: str, *, consent: bool) -> dict[str, str]:
        """Return this visitor's live facts; empty without consent or after the TTL."""
        ...

    def forget(self, visitor_key: str) -> int:
        """Erase everything keyed by the visitor and return the number of facts removed."""
        ...

    def rows_for(self, visitor_key: str) -> int:
        """Return the rows (store plus caches) still keyed by the visitor."""
        ...
