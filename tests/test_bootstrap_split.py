"""Characterization of the PVA-M4.1 split of `create_app` into wiring, lifespan and routes."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from fastapi.routing import iter_route_contexts
from fastapi.testclient import TestClient

from app.bootstrap import container, lifespan
from app.bootstrap.logging import _EVENTS
from app.bootstrap.wiring import ProviderResource
from tests.support import FixedClock, settings

if TYPE_CHECKING:
    from pathlib import Path


def test_lifespan_events_keep_the_allowlisted_logger_name() -> None:
    # The JSON formatter structures only allowlisted (logger, operation) pairs; a renamed
    # logger would silently turn retention, startup and shutdown lines into external events.
    assert lifespan.log.name == "app.bootstrap.container"
    assert {"retention", "startup", "shutdown"} <= set(_EVENTS[lifespan.log.name])


def test_container_keeps_its_public_names() -> None:
    assert container.ProviderResource is ProviderResource
    assert container.MAINTENANCE_SECONDS == lifespan.MAINTENANCE_SECONDS == 600


class _CatalogLoadError(Exception):
    pass


def test_failed_acquisition_still_closes_the_registry_then_the_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[str] = []
    real_build = container.build_persistence

    def spying_build(*args: object) -> object:
        persistence = real_build(*args)  # type: ignore[arg-type]
        database = persistence.database
        real_close = database.close

        async def close() -> None:
            events.append("database")
            await real_close()

        monkeypatch.setattr(database, "close", close)
        return persistence

    monkeypatch.setattr(container, "build_persistence", spying_build)
    app = container.create_app(settings(tmp_path), clock=FixedClock())
    services = app.state.services

    async def failing_load() -> None:
        raise _CatalogLoadError

    monkeypatch.setattr(services.catalog, "load", failing_load)
    real_registry_close = services.chat.registry.close

    def registry_close() -> None:
        events.append("registry")
        real_registry_close()

    monkeypatch.setattr(services.chat.registry, "close", registry_close)
    with pytest.raises(_CatalogLoadError), TestClient(app):
        pass
    assert events == ["registry", "database"]
    assert services.chat.registry.closing


def test_route_and_middleware_order_is_pinned(tmp_path: Path) -> None:
    app = container.create_app(settings(tmp_path), clock=FixedClock())
    # Outermost first at runtime: context, CORS, origin policy, body limit, routes.
    assert [m.cls.__name__ for m in app.user_middleware] == [
        "RequestContextMiddleware",
        "CORSMiddleware",
        "OriginMiddleware",
        "AnalyticsBodyLimitMiddleware",
    ]
    paths = {c.path for c in iter_route_contexts(app.routes) if c.path}
    assert not {p for p in paths if p.startswith("/internal/v1/ops/") and "analytics" not in p}
    with_token = container.create_app(
        settings(tmp_path, ops_read_token="o" * 32), clock=FixedClock()
    )
    private = {c.path for c in iter_route_contexts(with_token.routes) if c.path}
    assert {p for p in private if p.startswith("/internal/v1/ops/") and "analytics" not in p}
