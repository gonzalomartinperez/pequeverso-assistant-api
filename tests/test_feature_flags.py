"""PVA-M4-X: every assistant v2 flag defaults to off (assistant-experience.md section 7.5)."""

from __future__ import annotations

import dataclasses

import pytest

from app.application.flags import FeatureFlags

EXPECTED = {
    "memory",
    "blocks_v2",
    "progress_events",
    "early_blocks",
    "web_access",
    "semantic_cache",
    "model_router",
}


def test_all_flags_default_off() -> None:
    flags = FeatureFlags()
    assert {f.name for f in dataclasses.fields(flags)} == EXPECTED
    assert flags.enabled() == frozenset()


def test_enabled_lists_only_the_flags_that_are_on() -> None:
    assert FeatureFlags(blocks_v2=True, progress_events=True).enabled() == {
        "blocks_v2",
        "progress_events",
    }


def test_flags_are_immutable() -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        FeatureFlags().memory = True  # type: ignore[misc]
