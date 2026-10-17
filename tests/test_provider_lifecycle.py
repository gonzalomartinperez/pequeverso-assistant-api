"""Composition owns its SDK client; borrowed providers and persisted runs keep their owner."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.adapters import observability
from app.adapters.sqlite import database
from app.bootstrap import container
from app.domain.errors import FailureCode, RejectedError
from tests.support import ScriptedProvider, settings


class FakeSdk:
    """No transport, credentials or network: only ownership and stream cancellation."""

    def __init__(self, order: list[str], *, close_error: bool = False) -> None:
        self.order = order
        self.close_error = close_error
        self.closes = 0
        self.responses = self
        self.started = asyncio.Event()
        self.stream_closed = False

    async def create(self, **_kwargs: Any) -> FakeStream:
        return FakeStream(self)

    async def close(self) -> None:
        # The SDK stream and client have different close methods in the real SDK.
        # create() returns the separate stream below so this method counts only client closes.
        self.closes += 1
        self.order.append('provider')
        if self.close_error:
            raise RuntimeError('synthetic SDK close failure')


class FakeStream:
    def __init__(self, sdk: FakeSdk) -> None:
        self.sdk = sdk

    def __aiter__(self) -> FakeStream:
        return self

    async def __anext__(self) -> Any:
        self.sdk.started.set()
        await asyncio.Event().wait()
        raise StopAsyncIteration

    async def close(self) -> None:
        self.sdk.stream_closed = True
        self.sdk.order.append('stream')


def owned_app(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, close_error: bool = False, telemetry: bool = False
):
    order: list[str] = []
    sdk = FakeSdk(order, close_error=close_error)

    monkeypatch.setattr(container, 'AsyncOpenAI', lambda **_kwargs: sdk)
    instances: list[database.Database] = []

    class TrackedDatabase(database.Database):
        async def close(self) -> None:
            try:
                await super().close()
            finally:
                order.append('database')

    def make_database(path: str) -> database.Database:
        db = TrackedDatabase(path)
        instances.append(db)
        return db

    from app.bootstrap import persistence

    monkeypatch.setattr(persistence, 'Database', make_database)
    if telemetry:

        class FakeTelemetry:
            def __init__(self, **_kwargs: Any) -> None:
                pass

            def shutdown(self) -> None:
                order.append('telemetry')

        monkeypatch.setattr(observability, 'RuntimeTelemetry', FakeTelemetry)
    app = container.create_app(
        settings(
            tmp_path,
            observability_enabled=telemetry,
            ai_provider='openai',
            allow_paid_ai=True,
            openai_api_key='synthetic-test-value-never-used-on-network',
        )
    )
    return app, sdk, order, instances


def test_owned_sdk_client_closes_exactly_once_before_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    app, sdk, order, _ = owned_app(tmp_path, monkeypatch)
    with TestClient(app) as client:
        assert client.get('/health/ready').status_code == 200
        assert sdk.closes == 0
    assert sdk.closes == 1
    assert order == ['provider', 'database']


def test_sdk_close_failure_still_closes_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    app, sdk, order, _ = owned_app(tmp_path, monkeypatch, close_error=True)
    with pytest.raises(RuntimeError, match='synthetic SDK close failure'), TestClient(app):
        pass
    assert sdk.closes == 1
    assert order == ['provider', 'database']


def test_failed_database_acquisition_releases_owned_resources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    app, sdk, order, databases = owned_app(tmp_path, monkeypatch)

    def fail_migration(_connection: object) -> None:
        raise RuntimeError('synthetic migration failure')

    monkeypatch.setattr(database, '_migrate', fail_migration)
    try:
        with pytest.raises(RuntimeError, match='synthetic migration failure'), TestClient(app):
            pass
        assert sdk.closes == 1
        assert order == ['provider', 'database']
        assert databases[0]._connection is None
    finally:
        # Keep the original failing reproduction from leaking its own worker/connection.
        if 'database' not in order:
            asyncio.run(databases[0].close())


def test_borrowed_provider_is_not_closed_by_composition(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    class Borrowed(ScriptedProvider):
        owner_closes = 0

        async def close(self) -> None:
            self.owner_closes += 1

    def forbidden_factory(**_kwargs: Any) -> None:
        raise AssertionError('borrowed provider must not acquire an SDK client')

    monkeypatch.setattr(container, 'AsyncOpenAI', forbidden_factory)
    provider = Borrowed()
    with TestClient(container.create_app(settings(tmp_path), provider=provider)):
        pass
    assert provider.owner_closes == 0


def test_active_sdk_stream_drains_before_owned_client_and_database_close(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    app, sdk, order, _ = owned_app(tmp_path, monkeypatch)

    async def scenario() -> None:
        async with app.router.lifespan_context(app):
            services = app.state.services
            opened = await services.sessions.open(None, 'synthetic-client')
            run = await services.chat.start(
                opened.session,
                '¿Qué incluye Grafismo Fonético?',
                None,
                'owned-shutdown-test',
                'synthetic-client',
            )

            async def consume() -> None:
                try:
                    async for _event in run.events():
                        pass
                finally:
                    await run.aclose()

            pending = asyncio.create_task(consume())
            await asyncio.wait_for(sdk.started.wait(), timeout=2)
        await asyncio.wait_for(pending, timeout=2)
        assert sdk.stream_closed
        assert sdk.closes == 1
        assert order == ['stream', 'provider', 'database']
        assert len(services.chat.registry) == 0
        assert services.chat.registry.closing
        with pytest.raises(RejectedError) as error:
            await services.chat.start(
                opened.session,
                '¿Qué incluye Grafismo Fonético?',
                None,
                'after-shutdown-test',
                'synthetic-client',
            )
        assert error.value.code is FailureCode.DEPENDENCY_UNAVAILABLE

    asyncio.run(scenario())


def test_failed_provider_close_still_releases_database_and_owned_telemetry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    app, sdk, order, _ = owned_app(tmp_path, monkeypatch, close_error=True, telemetry=True)
    with pytest.raises(RuntimeError, match='synthetic SDK close failure'), TestClient(app):
        pass
    assert sdk.closes == 1
    assert order == ['provider', 'database', 'telemetry']
