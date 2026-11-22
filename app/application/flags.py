"""Assistant v2 feature flags (PVA-M4-X, ADR-0021, assistant-experience.md section 7.5).

`FeatureFlags` is the immutable per-run snapshot; the `Flags` port supplies it, so a run sees one
consistent set even when a DB-backed adapter changes flags at runtime. Every flag defaults to off
until its gate passes; breakers and the monthly hard stop are independent of flags.
`web_official_help` keeps its existing setting (`OFFICIAL_HELP_ENABLED`, ADR-0008).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

FLAG_NAMES = (
    "memory",
    "blocks_v2",
    "progress_events",
    "early_blocks",
    "web_access",
    "semantic_cache",
    "model_router",
)


@dataclass(frozen=True, slots=True)
class FeatureFlags:
    """Runtime switches for assistant v2 behaviour; all off by default."""

    memory: bool = False
    blocks_v2: bool = False
    progress_events: bool = False
    early_blocks: bool = False
    web_access: bool = False
    semantic_cache: bool = False
    model_router: bool = False

    def enabled(self) -> frozenset[str]:
        """Return the names of the flags that are on."""
        return frozenset(name for name in FLAG_NAMES if getattr(self, name))


class Flags(Protocol):
    """Source of the flag snapshot for one run."""

    async def current(self) -> FeatureFlags:
        """Return the flags in force now."""
        ...


class StaticFlags:
    """A fixed snapshot: the default (all off) until a DB-backed adapter exists."""

    def __init__(self, flags: FeatureFlags | None = None) -> None:
        self._flags = flags or FeatureFlags()

    async def current(self) -> FeatureFlags:
        """Return the fixed snapshot."""
        return self._flags
