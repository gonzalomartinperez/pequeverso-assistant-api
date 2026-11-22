"""Memory isolation contract (PVA-M2-X red tests, green since PVA-M4-X).

The properties come from assistant-experience.md section 6.4. They ran red against a deliberately
non-isolating stub until PVA-M4-X added the `MemoryStore` port (`app/application/memory_ports.py`)
and the in-memory adapter; `make_store` now returns the real adapter. The stub stays as a negative
control: every property must fail against it.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.adapters.memory.in_memory import InMemoryMemoryStore
from app.application.memory_ports import MEMORY_TTL, VisitorKey

TTL = timedelta(days=60)


class FakeClock:
    def __init__(self) -> None:
        self.current = datetime(2026, 11, 14, tzinfo=UTC)

    def now(self) -> datetime:
        return self.current


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


class SyncStore:
    """Drive the async port from these synchronous properties (shared with the sync stub)."""

    def __init__(self, store: InMemoryMemoryStore) -> None:
        self.store = store

    def write(self, visitor_key: str, key: str, value: str, *, consent: bool) -> bool:
        return asyncio.run(self.store.write(VisitorKey(visitor_key), key, value, consent=consent))

    def read(self, visitor_key: str, *, consent: bool) -> dict[str, str]:
        return asyncio.run(self.store.read(VisitorKey(visitor_key), consent=consent))

    def forget(self, visitor_key: str) -> int:
        return asyncio.run(self.store.forget(VisitorKey(visitor_key)))

    def rows_for(self, visitor_key: str) -> int:
        return asyncio.run(self.store.rows_for(VisitorKey(visitor_key)))


def make_store(clock: FakeClock) -> Any:
    """The real in-memory adapter; the PostgreSQL adapter will run the same properties."""
    return SyncStore(InMemoryMemoryStore(clock))


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def store(clock: FakeClock) -> Any:
    return make_store(clock)


def test_the_spy_records_every_port_call(clock: FakeClock) -> None:
    store = SpyStub(clock)
    store.write("visitor-a", "verbosity", "short", consent=True)
    store.read("visitor-a", consent=True)
    store.forget("visitor-a")
    assert store.calls == ["write", "read", "forget"]


def test_nothing_written_for_a_is_readable_by_b(store: Any) -> None:
    store.write("visitor-a", "child_age_band", "4-5", consent=True)
    assert store.read("visitor-b", consent=True) == {}
    assert store.read("visitor-a", consent=True) == {"child_age_band": "4-5"}


def test_consent_off_stores_and_returns_nothing(store: Any) -> None:
    accepted = store.write("visitor-a", "verbosity", "short", consent=False)
    assert accepted is False
    assert store.read("visitor-a", consent=True) == {}
    assert store.read("visitor-a", consent=False) == {}


def test_forget_is_complete_and_counts_what_was_shown(store: Any) -> None:
    store.write("visitor-a", "verbosity", "short", consent=True)
    store.write("visitor-a", "child_age_band", "4-5", consent=True)
    shown = len(store.read("visitor-a", consent=True))
    assert shown == 2  # positive control: a null store cannot satisfy the counts below
    assert store.forget("visitor-a") == shown
    assert store.read("visitor-a", consent=True) == {}
    assert store.rows_for("visitor-a") == 0


def test_forget_for_a_leaves_b_untouched(store: Any) -> None:
    store.write("visitor-a", "verbosity", "short", consent=True)
    store.write("visitor-b", "verbosity", "normal", consent=True)
    store.forget("visitor-a")
    assert store.read("visitor-b", consent=True) == {"verbosity": "normal"}


def test_facts_expire_after_the_fixed_ttl(store: Any, clock: FakeClock) -> None:
    store.write("visitor-a", "verbosity", "short", consent=True)
    clock.current += TTL - timedelta(seconds=1)
    assert store.read("visitor-a", consent=True) == {"verbosity": "short"}  # positive control
    clock.current += timedelta(seconds=2)  # past the TTL; the read above must not have extended it
    assert store.read("visitor-a", consent=True) == {}


def test_values_outside_the_enum_never_persist(store: Any) -> None:
    accepted = store.write("visitor-a", "free_text", "el kit cuesta 1 dólar", consent=True)
    assert accepted is False
    assert store.read("visitor-a", consent=True) == {}


def test_ttl_matches_the_port_constant() -> None:
    assert MEMORY_TTL == TTL


@pytest.mark.parametrize(
    "prop",
    [
        test_nothing_written_for_a_is_readable_by_b,
        test_consent_off_stores_and_returns_nothing,
        test_forget_is_complete_and_counts_what_was_shown,
        test_forget_for_a_leaves_b_untouched,
        test_values_outside_the_enum_never_persist,
    ],
)
def test_every_property_fails_against_the_non_isolating_stub(prop, clock: FakeClock) -> None:
    with pytest.raises(AssertionError):
        prop(SpyStub(clock))


def test_ttl_property_fails_against_the_non_isolating_stub(clock: FakeClock) -> None:
    with pytest.raises(AssertionError):
        test_facts_expire_after_the_fixed_ttl(SpyStub(clock), clock)


def test_each_fact_expires_from_its_own_write(store: Any, clock: FakeClock) -> None:
    # ADR-0021: per-fact expiry; a later write of another key does not extend an older fact.
    store.write("visitor-a", "verbosity", "short", consent=True)
    clock.current += TTL - timedelta(days=1)
    store.write("visitor-a", "audience_role", "parent", consent=True)
    clock.current += timedelta(days=2)
    assert store.read("visitor-a", consent=True) == {"audience_role": "parent"}


def test_retention_job_purges_expired_rows_for_every_visitor(clock: FakeClock) -> None:
    store = InMemoryMemoryStore(clock)
    asyncio.run(store.write(VisitorKey("visitor-a"), "verbosity", "short", consent=True))
    clock.current += TTL - timedelta(days=1)
    asyncio.run(store.write(VisitorKey("visitor-b"), "verbosity", "normal", consent=True))
    clock.current += timedelta(days=2)
    assert asyncio.run(store.purge_expired(clock.now())) == 1
    assert asyncio.run(store.rows_for(VisitorKey("visitor-a"))) == 0
    assert asyncio.run(store.rows_for(VisitorKey("visitor-b"))) == 1


def test_an_empty_visitor_key_is_refused(store: Any) -> None:
    assert store.write("", "verbosity", "short", consent=True) is False
    assert store.rows_for("") == 0
