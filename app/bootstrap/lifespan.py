"""Application lifespan: readiness, background loops, ordered acquisition and drain (PVA-M4.1)."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import TYPE_CHECKING

from app.adapters.postgres.database import PostgresDatabase
from app.bootstrap.logging import configure_logging, flush_external_events

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable

    from fastapi import FastAPI

    from app.application.catalog import CatalogService
    from app.application.chat import ChatService
    from app.application.knowledge import HybridKnowledgeRetrieval
    from app.application.product_analytics import AnalyticsService
    from app.bootstrap.persistence import Persistence
    from app.bootstrap.wiring import Wiring

# The JSON log allowlist (`app.bootstrap.logging._EVENTS`) keys these events by this name.
log = logging.getLogger("app.bootstrap.container")

MAINTENANCE_SECONDS = 600
SHUTDOWN_DRAIN_SECONDS = 10


def readiness(
    persistence: Persistence,
    chat: ChatService,
    catalog: CatalogService,
    analytics: AnalyticsService | None,
    knowledge: HybridKnowledgeRetrieval | None,
) -> Callable[[], Awaitable[bool]]:
    """Build the readiness probe; any dependency error reads as not ready."""
    db = persistence.database

    async def ready() -> bool:
        try:
            if chat.registry.closing or not await db.ping() or catalog.active is None:
                return False
            if isinstance(db, PostgresDatabase) and not await db.runtime_ownership_alive():
                return False
            if analytics is not None and not await analytics.repository.ready():
                return False
            return knowledge is None or (
                catalog.synchronized and await knowledge.ready(catalog.active)
            )
        except Exception:
            return False

    return ready


async def maintenance_loop(runtime: Wiring) -> None:
    """Purge expired sessions, rate windows and run metrics every maintenance period."""
    clock = runtime.clock
    while True:
        await asyncio.sleep(MAINTENANCE_SECONDS)
        try:
            purged = await runtime.sessions.purge_expired()
            await runtime.persistence.rates.purge(clock.now(), timedelta(days=2))
            await runtime.persistence.metrics.purge(clock.now())
            if purged:
                log.info('{"operation":"retention","sessions_deleted":%d}', purged)
        except Exception:
            log.exception('{"operation":"retention","outcome":"failed"}')


async def catalog_refresh_loop(runtime: Wiring) -> None:
    """Refresh the catalog snapshot on the configured period."""
    while True:
        await asyncio.sleep(runtime.settings.catalog_refresh_seconds)
        try:
            await runtime.catalog.refresh()
        except Exception:
            log.exception('{"operation":"catalog_refresh","outcome":"dependency_failed"}')


def _register_cleanups(resources: contextlib.AsyncExitStack, runtime: Wiring) -> None:
    # Register owned cleanup before acquisition: a migration can fail after opening SQLite.
    # ExitStack closes every resource even if another close raises, in reverse order.
    resources.callback(flush_external_events)
    if runtime.telemetry is not None:
        resources.push_async_callback(asyncio.to_thread, runtime.telemetry.shutdown)
    for database in runtime.persistence.resources:
        resources.push_async_callback(database.close)
    if runtime.provider.close is not None:
        resources.push_async_callback(runtime.provider.close)


async def _acquire(resources: contextlib.AsyncExitStack, runtime: Wiring) -> None:
    persistence = runtime.persistence
    db = persistence.database
    for database in persistence.resources:
        await database.open()
    if isinstance(db, PostgresDatabase):
        # Hold the dedicated connection until all streams and tasks have drained.
        # An overlapping instance must fail before touching another owner's runs.
        await resources.enter_async_context(db.runtime_ownership())
    if runtime.analytics is not None and not await runtime.analytics.repository.ready():
        raise RuntimeError("product analytics requires the exact offline schema migration")
    abandoned = await persistence.runs.abandon_active()
    await persistence.ledger.abandon_pending()
    if abandoned:
        log.info('{"operation":"startup","abandoned_runs":%d}', abandoned)
    await runtime.catalog.load()
    await runtime.catalog.refresh()
    await runtime.sessions.purge_expired()


async def _drain(runtime: Wiring) -> None:
    runtime.chat.registry.close()
    try:
        async with asyncio.timeout(SHUTDOWN_DRAIN_SECONDS):
            await runtime.cleanups.drain()
            await runtime.chat.registry.drain()
    except Exception:
        # Bound shutdown, preserve unknown spend and recover an interrupted run
        # conservatively if an exceptional finalizer cannot finish.
        log.exception('{"operation":"shutdown","outcome":"drain_failed"}')
        db = runtime.persistence.database
        if not isinstance(db, PostgresDatabase) or await db.runtime_ownership_alive():
            await runtime.persistence.runs.abandon_active()
            await runtime.persistence.ledger.abandon_pending()


async def _stop(tasks: list[asyncio.Task[None]]) -> None:
    for task in tasks:
        task.cancel()
    for task in tasks:
        with contextlib.suppress(asyncio.CancelledError):
            await task


def build_lifespan(
    runtime: Wiring,
) -> Callable[[FastAPI], contextlib.AbstractAsyncContextManager[None]]:
    """Own every resource for the application's lifetime, in a fixed acquisition order."""

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        configure_logging(stream=runtime.settings.log_stream)
        async with contextlib.AsyncExitStack() as resources:
            _register_cleanups(resources, runtime)
            tasks: list[asyncio.Task[None]] = []
            try:
                await _acquire(resources, runtime)
                tasks = [
                    asyncio.create_task(maintenance_loop(runtime)),
                    asyncio.create_task(catalog_refresh_loop(runtime)),
                ]
                yield
            finally:
                await _drain(runtime)
                await _stop(tasks)

    return lifespan
