"""Deploy-contract health aliases (ecosystem 8.5, ADR-0019, PVA-M3.3)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest

from app.adapters.sqlite.database import SCHEMA_LEVEL
from app.bootstrap.container import expected_schema_version
from tests.support import client

if TYPE_CHECKING:
    from pathlib import Path


def test_both_path_families_return_200_with_version(tmp_path: Path) -> None:
    with client(tmp_path, service_revision="abc1234") as c:
        assert c.get("/health/live").json() == {"status": "ok"}
        assert c.get("/health/ready").status_code == 200
        assert c.get("/healthz").json() == {"status": "ok", "version": "abc1234"}
        ready = c.get("/readyz")
        assert ready.status_code == 200
        body = ready.json()
        assert body["status"] == "ready"
        assert body["version"] == "abc1234"
        assert body["schema_version"] == f"sqlite-{SCHEMA_LEVEL}"
        assert body["catalog"] == c.get("/health/ready").json()["catalog"]


def test_unknown_revision_and_not_ready(tmp_path: Path) -> None:
    with client(tmp_path, catalog_file=tmp_path / "missing.json") as c:
        assert c.get("/healthz").json() == {"status": "ok", "version": "unknown"}
        ready = c.get("/readyz")
        assert ready.status_code == 503
        assert ready.json()["status"] == "not_ready"
        assert c.get("/health/ready").status_code == 503


def test_aliases_stay_out_of_the_public_openapi(tmp_path: Path) -> None:
    with client(tmp_path) as c:
        paths = c.app.openapi()["paths"]  # type: ignore[attr-defined]
    assert "/healthz" not in paths and "/readyz" not in paths


@pytest.mark.parametrize(
    ("storage", "analytics", "expected"),
    [
        ("sqlite", False, f"sqlite-{SCHEMA_LEVEL}"),
        ("postgres", False, "postgres-004"),
        ("postgres", True, "postgres-006"),
    ],
)
def test_expected_schema_version_follows_storage_and_analytics(
    storage: str, analytics: bool, expected: str
) -> None:
    settings = SimpleNamespace(application_storage=storage, product_analytics_enabled=analytics)
    assert expected_schema_version(settings) == expected  # type: ignore[arg-type]
