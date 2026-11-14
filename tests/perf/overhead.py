"""Overhead harness (PVA-M2-X): time named pipeline stages with an injectable clock.

`docs/master-plan/assistant-experience.md` section 1: server overhead excluding provider time is
gated by a deterministic lane (fake clock, stub provider that sleeps a fixed time). This module
only measures and reports; it never calls a model and imports nothing from `app`.
"""

from __future__ import annotations

import json
import math
import time
from collections import defaultdict
from contextlib import contextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator


def percentile(values: list[float], q: float) -> float:
    """Nearest-rank percentile (q in 0..100) of a non-empty list."""
    ordered = sorted(values)
    rank = max(1, math.ceil(q / 100 * len(ordered)))
    return ordered[rank - 1]


class OverheadHarness:
    """Collect per-stage durations (milliseconds) from a clock returning seconds."""

    def __init__(self, clock: Callable[[], float] = time.perf_counter) -> None:
        self._clock = clock
        self._samples: dict[str, list[float]] = defaultdict(list)

    @contextmanager
    def stage(self, name: str) -> Iterator[None]:
        """Time the enclosed block under `name`, even when it raises."""
        start = self._clock()
        try:
            yield
        finally:
            self._samples[name].append((self._clock() - start) * 1000)

    def report(self) -> dict[str, dict[str, float]]:
        """Return `{stage: {n, p50_ms, p95_ms}}` in first-seen stage order."""
        return {
            name: {
                "n": len(values),
                "p50_ms": round(percentile(values, 50), 3),
                "p95_ms": round(percentile(values, 95), 3),
            }
            for name, values in self._samples.items()
        }

    def to_json(self) -> str:
        """Serialize `report()` deterministically."""
        return json.dumps(self.report(), sort_keys=True, indent=2)
