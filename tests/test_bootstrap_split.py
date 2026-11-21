"""Characterization of the PVA-M4.1 split of `create_app` into wiring, lifespan and routes."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from types import SimpleNamespace
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


class _Probe:
    def __init__(self, **results: object) -> None:
        self.results = results

    def __getattr__(self, name: str) -> object:
        value = self.results[name]

        async def call(*_args: object) -> object:
            if isinstance(value, BaseException):
                raise value
            return value

        return call


def _readiness(**overrides: object) -> bool:
    parts: dict[str, object] = {
        "closing": False,
        "db": _Probe(ping=True),
        "active": object(),
        "analytics": None,
        "knowledge": None,
        "synchronized": True,
    }
    parts.update(overrides)
    persistence = SimpleNamespace(database=parts["db"])
    chat = SimpleNamespace(registry=SimpleNamespace(closing=parts["closing"]))
    catalog = SimpleNamespace(active=parts["active"], synchronized=parts["synchronized"])
    probe = lifespan.readiness(
        persistence,  # type: ignore[arg-type]
        chat,  # type: ignore[arg-type]
        catalog,  # type: ignore[arg-type]
        parts["analytics"],  # type: ignore[arg-type]
        parts["knowledge"],  # type: ignore[arg-type]
    )
    return asyncio.run(probe())


def test_readiness_reads_every_dependency_and_fails_closed() -> None:
    assert _readiness() is True
    assert _readiness(closing=True) is False
    assert _readiness(db=_Probe(ping=False)) is False
    assert _readiness(active=None) is False
    assert _readiness(db=_Probe(ping=RuntimeError("down"))) is False
    analytics = SimpleNamespace(repository=_Probe(ready=False))
    assert _readiness(analytics=analytics) is False
    assert _readiness(knowledge=_Probe(ready=True)) is True
    assert _readiness(knowledge=_Probe(ready=True), synchronized=False) is False
    assert _readiness(knowledge=_Probe(ready=False)) is False


def test_maintenance_loop_purges_logs_and_survives_failures(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(lifespan, "MAINTENANCE_SECONDS", 0)
    calls: list[str] = []
    done = asyncio.Event()
    purged = iter([2, RuntimeError("store down"), 0])

    async def purge_expired() -> int:
        value = next(purged)
        if isinstance(value, BaseException):
            raise value
        return value

    async def purge(*_args: object) -> None:
        calls.append("purge")
        if len(calls) >= 4:
            done.set()

    clock = FixedClock()
    wiring = SimpleNamespace(
        clock=clock,
        sessions=SimpleNamespace(purge_expired=purge_expired),
        persistence=SimpleNamespace(
            rates=SimpleNamespace(purge=purge), metrics=SimpleNamespace(purge=purge)
        ),
    )

    async def run() -> None:
        task = asyncio.create_task(lifespan.maintenance_loop(wiring))  # type: ignore[arg-type]
        await done.wait()
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    with caplog.at_level(logging.INFO, logger="app.bootstrap.container"):
        asyncio.run(run())
    messages = [record.getMessage() for record in caplog.records]
    assert '{"operation":"retention","sessions_deleted":2}' in messages
    assert '{"operation":"retention","outcome":"failed"}' in messages


def test_official_help_and_composer_wrapping_are_wired_only_when_enabled(
    tmp_path: Path,
) -> None:
    clock = FixedClock()
    enabled = SimpleNamespace(
        official_help_enabled=True, ai_provider="openai", assistant_enabled=True
    )
    assert container._official_help(enabled, clock) is not None  # type: ignore[arg-type]
    for change in ({"official_help_enabled": False}, {"ai_provider": "fixture"}):
        disabled = SimpleNamespace(**(vars(enabled) | change))
        assert container._official_help(disabled, clock) is None  # type: ignore[arg-type]
    wrapped = object()
    owned = ProviderResource(
        container.FixtureProvider(),
        wrap_composer=lambda _composer: wrapped,  # type: ignore[arg-type,return-value]
    )
    config = settings(tmp_path)
    persistence = container.build_persistence(config, container.CatalogParser(frozenset()))
    composer, knowledge = container._composer_and_knowledge(config, persistence, owned, clock)
    assert composer is wrapped
    assert knowledge is None
