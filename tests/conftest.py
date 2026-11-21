"""Test lanes: every test is either ``unit`` (no external service) or ``services``.

In this suite a ``skipif`` marker is used only to gate tests on an explicitly isolated real
PostgreSQL or Neo4j fixture, so any test carrying one is classified as ``services``; every other
test is ``unit``. ``uv run pytest -m unit -n auto`` is the fast local lane.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

import pytest
from hypothesis import HealthCheck, settings

from app.bootstrap import logging as app_logging

if TYPE_CHECKING:
    from collections.abc import Iterator


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        lane = "services" if item.get_closest_marker("skipif") else "unit"
        item.add_marker(getattr(pytest.mark, lane))


@pytest.fixture(autouse=True)
def _restore_logging_state() -> Iterator[None]:
    """CLI `main()` calls switch logging to stderr process-wide; never leak that across tests."""
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    use_stderr, external = app_logging._use_stderr, app_logging._external
    yield
    app_logging._use_stderr, app_logging._external = use_stderr, external
    root.handlers[:] = handlers
    root.setLevel(level)


settings.register_profile(
    "ci",
    max_examples=100,
    deadline=None,
    derandomize=True,
    print_blob=True,
    suppress_health_check=[HealthCheck.too_slow],
)
settings.register_profile(
    "nightly",
    max_examples=1000,
    deadline=None,
    print_blob=True,
    suppress_health_check=[HealthCheck.too_slow],
)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "ci"))
