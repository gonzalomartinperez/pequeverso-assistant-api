"""Assistant v2 feature flags (PVA-M4-X, assistant-experience.md section 7.5).

Every flag defaults to off until its gate passes; breakers and the monthly hard stop are
independent of flags. `web_official_help` keeps its existing setting (`OFFICIAL_HELP_ENABLED`,
ADR-0008) and is not duplicated here.
"""

from __future__ import annotations

from dataclasses import dataclass, fields


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
        return frozenset(f.name for f in fields(self) if getattr(self, f.name))
