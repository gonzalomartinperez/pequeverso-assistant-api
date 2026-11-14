"""Memory isolation contract on a spy port (PVA-M2-X), red until PVA-M4-X.

The `MemoryStore` port is defined here, not in `app/`, from assistant-experience.md section 6. The
tests run against a deliberately non-isolating stub, so each isolation property fails on its own
assertion (strict xfail with `raises=AssertionError`). PVA-M4-X replaces `make_store` with the real
in-memory adapter and removes the markers.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Protocol

import pytest

TTL = timedelta(days=60)
RED = pytest.mark.xfail(strict=True, raises=AssertionError, reason="PVA-M4-X turns these green")


class MemoryStore(Protocol):
    """Closed-schema visitor memory; `visitor_key` comes from the session only."""

    def write(self, visitor_key: str, key: str, value: str, *, consent: bool) -> bool:
        """Store one enumerated fact; False when refused (no consent or outside the enum)."""

    def read(self, visitor_key: str, *, consent: bool) -> dict[str, str]:
        """Return that visitor's facts (empty without consent or after the TTL)."""

    def forget(self, visitor_key: str) -> int:
        """Erase everything keyed by the visitor and return the number of rows removed."""

    def rows_for(self, visitor_key: str) -> int:
        """Rows (store plus caches) still keyed by the visitor, for forget completeness."""


class FakeClock:
    def __init__(self) -> None:
        self.now = datetime(2026, 11, 14, tzinfo=UTC)


class SpyStub:
    """Non-isolating on purpose: one shared dict, consent ignored, TTL ignored, leaky cache."""

    def __init__(self, clock: FakeClock) -> None:
        self.clock = clock
        self.calls: list[str] = []
        self._shared: dict[str, str] = {}
        self._cache: dict[str, dict[str, str]] = {}

    def write(self, visitor_key: str, key: str, value: str, *, consent: bool) -> bool:
        self.calls.append("write")
        self._shared[key] = value
        self._cache[visitor_key] = dict(self._shared)
        return True

    def read(self, visitor_key: str, *, consent: bool) -> dict[str, str]:
        self.calls.append("read")
        return dict(self._shared)

    def forget(self, visitor_key: str) -> int:
        self.calls.append("forget")
        removed = len(self._shared)
        self._shared.clear()
        return removed

    def rows_for(self, visitor_key: str) -> int:
        return len(self._cache.get(visitor_key, {}))


def make_store(clock: FakeClock) -> MemoryStore:
    """The seam PVA-M4-X swaps for the real adapter."""
    return SpyStub(clock)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def store(clock: FakeClock) -> MemoryStore:
    return make_store(clock)


def test_the_spy_records_every_port_call(clock: FakeClock) -> None:
    store = SpyStub(clock)
    store.write("visitor-a", "verbosity", "short", consent=True)
    store.read("visitor-a", consent=True)
    store.forget("visitor-a")
    assert store.calls == ["write", "read", "forget"]


@RED
def test_nothing_written_for_a_is_readable_by_b(store: MemoryStore) -> None:
    store.write("visitor-a", "child_age_band", "4-5", consent=True)
    assert store.read("visitor-b", consent=True) == {}
    assert store.read("visitor-a", consent=True) == {"child_age_band": "4-5"}


@RED
def test_consent_off_stores_and_returns_nothing(store: MemoryStore) -> None:
    accepted = store.write("visitor-a", "verbosity", "short", consent=False)
    assert accepted is False
    assert store.read("visitor-a", consent=True) == {}
    assert store.read("visitor-a", consent=False) == {}


@RED
def test_forget_is_complete_and_counts_what_was_shown(store: MemoryStore) -> None:
    store.write("visitor-a", "verbosity", "short", consent=True)
    store.write("visitor-a", "child_age_band", "4-5", consent=True)
    shown = len(store.read("visitor-a", consent=True))
    assert shown == 2  # positive control: a null store cannot satisfy the counts below
    assert store.forget("visitor-a") == shown
    assert store.read("visitor-a", consent=True) == {}
    assert store.rows_for("visitor-a") == 0


@RED
def test_forget_for_a_leaves_b_untouched(store: MemoryStore) -> None:
    store.write("visitor-a", "verbosity", "short", consent=True)
    store.write("visitor-b", "verbosity", "normal", consent=True)
    store.forget("visitor-a")
    assert store.read("visitor-b", consent=True) == {"verbosity": "normal"}


@RED
def test_facts_expire_after_the_fixed_ttl(store: MemoryStore, clock: FakeClock) -> None:
    store.write("visitor-a", "verbosity", "short", consent=True)
    clock.now += TTL - timedelta(seconds=1)
    assert store.read("visitor-a", consent=True) == {"verbosity": "short"}  # positive control
    clock.now += timedelta(seconds=2)  # past the TTL; the read above must not have extended it
    assert store.read("visitor-a", consent=True) == {}


@RED
def test_values_outside_the_enum_never_persist(store: MemoryStore) -> None:
    accepted = store.write("visitor-a", "free_text", "el kit cuesta 1 dólar", consent=True)
    assert accepted is False
    assert store.read("visitor-a", consent=True) == {}
