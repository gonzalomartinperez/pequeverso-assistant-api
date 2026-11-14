"""The overhead harness reports p50 and p95 per stage, driven by a fake clock (PVA-M2-X)."""

from __future__ import annotations

import json

import pytest

from tests.perf.overhead import OverheadHarness, percentile


class FakeClock:
    """Each stage run consumes the next scripted duration in seconds."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _drive(harness: OverheadHarness, clock: FakeClock, stage: str, millis: list[int]) -> None:
    for ms in millis:
        with harness.stage(stage):
            clock.advance(ms / 1000)


def test_reports_p50_and_p95_per_stage() -> None:
    clock = FakeClock()
    harness = OverheadHarness(clock)
    _drive(harness, clock, "retrieve", list(range(1, 101)))  # 1..100 ms
    _drive(harness, clock, "validate", [10, 20, 30, 40])
    report = harness.report()
    assert list(report) == ["retrieve", "validate"]
    assert report["retrieve"] == {"n": 100, "p50_ms": 50.0, "p95_ms": 95.0}
    assert report["validate"] == {"n": 4, "p50_ms": 20.0, "p95_ms": 40.0}
    assert json.loads(harness.to_json()) == report


def _fail_after(clock: FakeClock, seconds: float) -> None:
    clock.advance(seconds)
    raise RuntimeError("provider failed")


def test_a_failing_stage_is_still_timed() -> None:
    clock = FakeClock()
    harness = OverheadHarness(clock)
    with pytest.raises(RuntimeError), harness.stage("compose"):
        _fail_after(clock, 0.25)
    assert harness.report()["compose"] == {"n": 1, "p50_ms": 250.0, "p95_ms": 250.0}


def test_percentile_edges() -> None:
    assert percentile([7.0], 95) == 7.0
    assert percentile([3.0, 1.0, 2.0], 0) == 1.0
    assert percentile([3.0, 1.0, 2.0], 100) == 3.0


def test_default_clock_is_real_and_monotonic() -> None:
    harness = OverheadHarness()
    with harness.stage("noop"):
        pass
    assert harness.report()["noop"]["p50_ms"] >= 0.0
