"""Composition root: builds adapters and use cases, owns their lifecycle (FastAPI lifespan)."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import ipaddress
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from openai import AsyncOpenAI

from app.adapters.catalog_schema import CatalogParser
from app.adapters.catalog_source import FileCatalogSource, HttpCatalogSource
from app.adapters.fixture_provider import FixtureProvider
from app.adapters.openai_provider import OpenAIResponsesProvider
from app.adapters.sqlite.catalog_repository import SqliteCatalogRepository
from app.adapters.sqlite.database import Database
from app.adapters.sqlite.ledger import SqliteLedger, SqliteRateLimiter
from app.adapters.sqlite.operations import SqliteOperationsQueries, SqliteRunMetrics
from app.adapters.sqlite.stores import SqliteMessageStore, SqliteRunStore, SqliteSessionStore
from app.ai.composer import ComposerSettings, GroundedComposer
from app.ai.provider import ModelProvider
from app.application.catalog import CatalogService
from app.application.chat import ChatLimits, ChatService
from app.application.operations import OperationsService, ServiceInfo
from app.application.ports import CatalogSource, Clock
from app.application.runs import RunRegistry
from app.application.sessions import SessionLimits, SessionService
from app.bootstrap.config import Settings, get_settings
from app.bootstrap.logging import configure_logging
from app.domain.budget import BudgetPolicy, Pricing, to_micro
from app.presentation.http import CookiePolicy, HttpSettings, Services, health, install_error_handlers, router
from app.presentation.middleware import BodyLimitMiddleware, OriginMiddleware, RequestContextMiddleware
from app.presentation.operations import build_router as build_operations_router
from app.presentation.streaming import ResponseCleanups

log = logging.getLogger(__name__)
MAINTENANCE_SECONDS = 600


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


def build_provider(settings: Settings) -> ModelProvider:
    if settings.ai_provider == 'openai':
        assert settings.openai_api_key is not None
        client = AsyncOpenAI(
            api_key=settings.openai_api_key.get_secret_value(),
            base_url='https://api.openai.com/v1',
            timeout=settings.openai_timeout_seconds,
            max_retries=0,
        )
        return OpenAIResponsesProvider(
            client, settings.openai_model, settings.openai_reasoning_effort, settings.openai_max_retries
        )
    return FixtureProvider(chunk_delay_seconds=settings.fixture_chunk_delay_ms / 1000)


def build_catalog_source(settings: Settings) -> CatalogSource:
    hosts = frozenset(settings.catalog_allowed_hosts)
    if settings.catalog_url:
        return HttpCatalogSource(settings.catalog_url, hosts)
    return FileCatalogSource(settings.catalog_file)


def create_app(
    settings: Settings | None = None,
    *,
    provider: ModelProvider | None = None,
    catalog_source: CatalogSource | None = None,
    clock: Clock | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    if provider is not None and settings.environment == 'production':
        raise ValueError('provider overrides are for tests and fixtures only')
    clock = clock or SystemClock()
    db = Database(settings.database_path)
    stores_rate = SqliteRateLimiter(db)
    sessions_store = SqliteSessionStore(db)
    messages = SqliteMessageStore(db)
    runs = SqliteRunStore(db)
    catalog = CatalogService(
        catalog_source or build_catalog_source(settings),
        CatalogParser(frozenset(settings.catalog_allowed_hosts)),
        SqliteCatalogRepository(db),
        clock,
        timedelta(hours=settings.catalog_price_max_age_hours),
    )
    session_service = SessionService(
        sessions_store,
        messages,
        stores_rate,
        clock,
        SessionLimits(
            retention=timedelta(hours=settings.session_retention_hours),
            bootstraps_per_hour=settings.sessions_per_client_per_hour,
            history_restore=40,
        ),
    )
    model = provider or build_provider(settings)
    ledger = SqliteLedger(db)
    run_metrics = SqliteRunMetrics(db)
    cleanups = ResponseCleanups()
    budget = BudgetPolicy(
        monthly_limit_micro=to_micro(settings.monthly_budget_usd),
        safety_margin=settings.budget_safety_margin,
        daily_limit_micro=to_micro(settings.daily_budget_usd),
    )
    chat = ChatService(
        composer=GroundedComposer(
            model, ComposerSettings(settings.max_output_tokens, settings.max_evidence_chars)
        ),
        catalog=catalog,
        messages=messages,
        runs=runs,
        ledger=ledger,
        metrics=run_metrics,
        rate_limiter=stores_rate,
        registry=RunRegistry(),
        clock=clock,
        pricing=Pricing(
            settings.price_input_per_million,
            settings.price_cached_input_per_million,
            settings.price_cache_write_per_million,
            settings.price_output_per_million,
        ),
        budget=budget,
        limits=ChatLimits(
            enabled=settings.assistant_enabled,
            max_message_chars=settings.max_message_chars,
            history_messages=settings.history_messages,
            messages_per_session_per_day=settings.messages_per_session_per_day,
            messages_per_client_per_hour=settings.messages_per_client_per_hour,
            max_concurrent_runs=settings.max_concurrent_runs,
            run_timeout=timedelta(seconds=settings.run_timeout_seconds),
            max_input_tokens=settings.max_input_tokens,
            max_output_tokens=settings.max_output_tokens,
        ),
    )

    operations = OperationsService(
        SqliteOperationsQueries(db),
        catalog,
        catalog.live,
        clock,
        budget,
        ServiceInfo(
            environment=settings.environment,
            revision=settings.service_revision,
            provider=settings.ai_provider,
            model=model.model,
            reasoning_effort=settings.openai_reasoning_effort if settings.ai_provider == 'openai' else 'n/a',
            assistant_enabled=settings.assistant_enabled,
            started_at=clock.now(),
            price_max_age_hours=settings.catalog_price_max_age_hours,
            pricing={
                'revision': settings.pricing_revision,
                'model': settings.openai_model,
                'input_per_million': str(settings.price_input_per_million),
                'cached_input_per_million': str(settings.price_cached_input_per_million),
                'cache_write_per_million': str(settings.price_cache_write_per_million),
                'output_per_million': str(settings.price_output_per_million),
            },
        ),
        chat.availability,
    )

    async def ready() -> bool:
        try:
            return not chat.registry.closing and await db.ping() and catalog.active is not None
        except Exception:  # noqa: BLE001
            return False

    async def maintenance() -> None:
        while True:
            await asyncio.sleep(MAINTENANCE_SECONDS)
            try:
                purged = await session_service.purge_expired()
                await stores_rate.purge(clock.now(), timedelta(days=2))
                await run_metrics.purge(clock.now())
                if purged:
                    log.info('{"operation":"retention","sessions_deleted":%d}', purged)
            except Exception:
                log.exception('{"operation":"retention","outcome":"failed"}')

    async def refresh_catalog() -> None:
        while True:
            await asyncio.sleep(settings.catalog_refresh_seconds)
            await catalog.refresh()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        configure_logging()
        await db.open()
        tasks: list[asyncio.Task[None]] = []
        try:
            abandoned = await runs.abandon_active()
            await ledger.abandon_pending()
            if abandoned:
                log.info('{"operation":"startup","abandoned_runs":%d}', abandoned)
            await catalog.load()
            await catalog.refresh()
            await session_service.purge_expired()
            tasks = [asyncio.create_task(maintenance()), asyncio.create_task(refresh_catalog())]
            yield
        finally:
            chat.registry.close()
            try:
                async with asyncio.timeout(10):
                    await cleanups.drain()
                    await chat.registry.drain()
            except Exception:
                # Bound shutdown, preserve unknown spend and recover an interrupted run
                # conservatively if an exceptional finalizer cannot finish.
                log.exception('{"operation":"shutdown","outcome":"drain_failed"}')
                await runs.abandon_active()
                await ledger.abandon_pending()
            for task in tasks:
                task.cancel()
            for task in tasks:
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            await db.close()

    app = FastAPI(
        title='Pequeverso assistant API',
        version='1',
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url='/api/v1/openapi.json' if settings.environment != 'production' else None,
    )
    app.state.services = Services(
        sessions=session_service,
        chat=chat,
        catalog=catalog,
        clock=clock,
        ready=ready,
        cleanups=cleanups,
        settings=HttpSettings(
            cookie=CookiePolicy(
                name=settings.cookie_name,
                secure=settings.session_cookie_secure,
                samesite=settings.session_cookie_samesite,
                max_age_seconds=settings.session_retention_hours * 3600,
            ),
            trusted_proxies=tuple(ipaddress.ip_network(c) for c in settings.trusted_proxy_cidrs),
            client_hash_key=settings.client_hash_key.get_secret_value().encode(),
            heartbeat_seconds=settings.heartbeat_seconds,
            max_message_chars=settings.max_message_chars,
            messages_per_day=settings.messages_per_session_per_day,
        ),
    )
    app.include_router(router)
    app.include_router(health)
    if settings.ops_read_token is not None:
        digest = hashlib.sha256(settings.ops_read_token.get_secret_value().encode()).digest()
        app.include_router(build_operations_router(operations, digest))
    install_error_handlers(app)
    # Outermost first at runtime: context → CORS → origin policy → body limit → routes.
    app.add_middleware(BodyLimitMiddleware, max_bytes=settings.max_body_bytes)
    app.add_middleware(OriginMiddleware, allowed_origins=settings.allowed_origins)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=['GET', 'POST', 'DELETE'],
        allow_headers=['Content-Type', 'X-CSRF-Token', 'Idempotency-Key', 'X-Request-ID'],
        expose_headers=['X-Request-ID', 'X-Run-ID', 'Retry-After'],
        max_age=600,
    )
    app.add_middleware(RequestContextMiddleware)
    return app
