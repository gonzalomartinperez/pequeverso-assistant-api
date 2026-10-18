"""Composition root: builds adapters and use cases, owns their lifecycle (FastAPI lifespan)."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import ipaddress
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.adapters.observability.telemetry import RuntimeTelemetry

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.routing import iter_route_contexts
from openai import AsyncOpenAI

from app.adapters.catalog.knowledge import PARSER_VERSION
from app.adapters.catalog_schema import CatalogParser
from app.adapters.catalog_source import FileCatalogSource, HttpCatalogSource
from app.adapters.graph.composer import GraphAnswerComposer
from app.adapters.official_help import OfficialHelpReader
from app.adapters.postgres.database import PostgresDatabase
from app.adapters.postgres.knowledge import PostgresKnowledgeStore
from app.adapters.postgres.product_analytics import PostgresProductAnalytics
from app.adapters.providers.fixture_provider import FixtureProvider
from app.adapters.providers.openai_embeddings import FixtureHashEmbeddings, OpenAIEmbeddings
from app.adapters.providers.openai_provider import OpenAIResponsesProvider
from app.ai.composer import ComposerSettings, GroundedComposer
from app.ai.provider import ModelProvider
from app.application.catalog import CatalogService
from app.application.chat import ChatLimits, ChatService
from app.application.embedding_budget import SharedEmbeddingAccounting
from app.application.knowledge import HybridKnowledgeRetrieval
from app.application.knowledge_ports import EmbeddingAccounting, Embeddings
from app.application.operations import OperationsService, ServiceInfo
from app.application.ports import AnswerComposer, CatalogSource, Clock
from app.application.product_analytics import AnalyticsService
from app.application.runs import RunRegistry
from app.application.sessions import SessionLimits, SessionService
from app.bootstrap.config import Settings, get_settings
from app.bootstrap.logging import configure_logging
from app.bootstrap.persistence import build_persistence
from app.bootstrap.provider_transport import close_owned_provider, provider_http_client
from app.domain.budget import BudgetPolicy, Pricing, to_micro
from app.presentation.http import CookiePolicy, HttpSettings, Services, health, install_error_handlers, router
from app.presentation.middleware import OriginMiddleware, RequestContextMiddleware
from app.presentation.operations import build_router as build_operations_router
from app.presentation.product_analytics import AnalyticsBodyLimitMiddleware
from app.presentation.product_analytics import build_router as build_analytics_router
from app.presentation.streaming import ResponseCleanups

log = logging.getLogger(__name__)
MAINTENANCE_SECONDS = 600


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class ProviderResource:
    """Only composition owns the client cleanup; use cases receive the provider port."""

    provider: ModelProvider
    close: Callable[[], Awaitable[None]] | None = None
    embeddings: Embeddings | None = None
    wrap_composer: Callable[[AnswerComposer], AnswerComposer] | None = None


_ProviderResource = ProviderResource  # Retain existing fixture callers and lifecycle contracts.
ProviderFactory = Callable[[Settings, EmbeddingAccounting], ProviderResource]


def build_provider(
    settings: Settings, embedding_accounting: EmbeddingAccounting | None = None
) -> _ProviderResource:
    if settings.ai_provider == 'openai':
        assert settings.openai_api_key is not None
        http = provider_http_client()
        client = AsyncOpenAI(
            http_client=http,
            api_key=settings.openai_api_key.get_secret_value(),
            base_url='https://api.openai.com/v1',
            timeout=settings.openai_timeout_seconds,
            max_retries=0,
        )
        embeddings: Embeddings | None = None
        if settings.knowledge_backend == 'graphrag':
            assert embedding_accounting is not None
            embeddings = OpenAIEmbeddings(client, embedding_accounting)
        return _ProviderResource(
            OpenAIResponsesProvider(
                client, settings.openai_model, settings.openai_reasoning_effort, settings.openai_max_retries
            ),
            lambda: close_owned_provider(client, http),
            embeddings,
        )
    return _ProviderResource(
        FixtureProvider(chunk_delay_seconds=settings.fixture_chunk_delay_ms / 1000),
        embeddings=FixtureHashEmbeddings() if settings.knowledge_backend == 'graphrag' else None,
    )


def build_catalog_source(settings: Settings) -> CatalogSource:
    hosts = frozenset(settings.catalog_allowed_hosts)
    if settings.catalog_url:
        return HttpCatalogSource(settings.catalog_url, hosts)
    return FileCatalogSource(settings.catalog_file)


def create_app(
    settings: Settings | None = None,
    *,
    provider: ModelProvider | None = None,
    provider_factory: ProviderFactory | None = None,
    catalog_source: CatalogSource | None = None,
    clock: Clock | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    if provider is not None and provider_factory is not None:
        raise ValueError('provider and provider_factory overrides are mutually exclusive')
    if (provider is not None or provider_factory is not None) and settings.environment == 'production':
        raise ValueError('provider overrides are for tests and fixtures only')
    clock = clock or SystemClock()
    parser = CatalogParser(frozenset(settings.catalog_allowed_hosts))
    persistence = build_persistence(settings, parser)
    db = persistence.database
    analytics: AnalyticsService | None = None
    if settings.product_analytics_enabled:
        assert isinstance(db, PostgresDatabase)
        analytics = AnalyticsService(PostgresProductAnalytics(db), synthetic=True)
    stores_rate = persistence.rates
    sessions_store = persistence.sessions
    messages = persistence.messages
    runs = persistence.runs
    catalog = CatalogService(
        catalog_source or build_catalog_source(settings),
        parser,
        persistence.catalog,
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
    ledger = persistence.ledger
    run_metrics = persistence.metrics
    cleanups = ResponseCleanups()
    budget = BudgetPolicy(
        monthly_limit_micro=to_micro(settings.monthly_budget_usd),
        safety_margin=settings.budget_safety_margin,
        daily_limit_micro=to_micro(settings.daily_budget_usd),
    )
    accounting = SharedEmbeddingAccounting(ledger, clock, budget, settings.embedding_input_price_per_million)
    if provider_factory is not None:
        owned_provider = provider_factory(settings, accounting)
    elif provider is not None:
        owned_provider = _ProviderResource(provider)
    else:
        owned_provider = build_provider(settings, accounting)
    model = owned_provider.provider
    grounded = GroundedComposer(
        model,
        ComposerSettings(settings.max_output_tokens, settings.max_evidence_chars, settings.max_input_tokens),
    )
    composer: AnswerComposer = grounded
    knowledge: HybridKnowledgeRetrieval | None = None
    if settings.knowledge_backend == 'graphrag':
        assert persistence.graph is not None
        assert isinstance(persistence.catalog, PostgresKnowledgeStore)
        embeddings = owned_provider.embeddings
        if embeddings is None and settings.ai_provider == 'fixture':
            embeddings = FixtureHashEmbeddings()
        assert embeddings is not None
        knowledge = HybridKnowledgeRetrieval(
            persistence.catalog, persistence.graph, embeddings, PARSER_VERSION, clock
        )
        composer = GraphAnswerComposer(grounded, knowledge, settings.max_input_tokens)
    if owned_provider.wrap_composer is not None:
        composer = owned_provider.wrap_composer(composer)
    chat = ChatService(
        official_help=(
            OfficialHelpReader()
            if settings.official_help_enabled
            and settings.ai_provider == 'openai'
            and settings.assistant_enabled
            else None
        ),
        composer=composer,
        knowledge=knowledge,
        runtime_ownership=db.runtime_ownership_alive if isinstance(db, PostgresDatabase) else None,
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

    operations_queries = persistence.operations
    operations = OperationsService(
        operations_queries,
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
            if chat.registry.closing or not await db.ping() or catalog.active is None:
                return False
            if isinstance(db, PostgresDatabase) and not await db.runtime_ownership_alive():
                return False
            if analytics is not None and not await analytics.repository.ready():
                return False
            return knowledge is None or (catalog.synchronized and await knowledge.ready(catalog.active))
        except Exception:  # noqa: BLE001
            return False

    telemetry: RuntimeTelemetry | None = None
    if settings.observability_enabled:
        from app.adapters.observability.telemetry import RuntimeTelemetry

        telemetry = RuntimeTelemetry(
            started_at=clock.now(),
            synthetic=settings.ai_provider == 'fixture',
            revision=settings.service_revision,
            ready=ready,
            active_runs=lambda: len(chat.registry),
            max_runs=settings.max_concurrent_runs,
            run_window=lambda: operations_queries.run_window(clock.now() - timedelta(hours=24)),
            endpoint=settings.telemetry_otlp_endpoint,
            sampling_ratio=settings.telemetry_trace_sampling_ratio,
            export_timeout=settings.telemetry_export_timeout_seconds,
        )

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
            try:
                await catalog.refresh()
            except Exception:
                log.exception('{"operation":"catalog_refresh","outcome":"dependency_failed"}')

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        configure_logging()
        # Register owned cleanup before acquisition: a migration can fail after opening SQLite.
        # ExitStack closes every resource even if another close raises, in reverse order.
        async with contextlib.AsyncExitStack() as resources:
            if telemetry is not None:
                resources.push_async_callback(asyncio.to_thread, telemetry.shutdown)
            for database in persistence.resources:
                resources.push_async_callback(database.close)
            if owned_provider.close is not None:
                resources.push_async_callback(owned_provider.close)
            tasks: list[asyncio.Task[None]] = []
            try:
                for database in persistence.resources:
                    await database.open()
                if isinstance(db, PostgresDatabase):
                    # Hold the dedicated connection until all streams and tasks have drained.
                    # An overlapping instance must fail before touching another owner's runs.
                    await resources.enter_async_context(db.runtime_ownership())
                if analytics is not None and not await analytics.repository.ready():
                    raise RuntimeError('product analytics requires the exact offline schema migration')
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
                    if not isinstance(db, PostgresDatabase) or await db.runtime_ownership_alive():
                        await runs.abandon_active()
                        await ledger.abandon_pending()
                for task in tasks:
                    task.cancel()
                for task in tasks:
                    with contextlib.suppress(asyncio.CancelledError):
                        await task

    app = FastAPI(
        title='Pequeverso assistant API',
        version='1',
        lifespan=lifespan,
        # Only the explicit, content-free application telemetry may instrument requests.
        # FastAPI 0.142 introduces native instrumentation enabled by default.
        telemetry={
            'tracing': False,
            'metrics': False,
            'logs': False,
            'operation_spans': False,
            'auto_configure': False,
        },
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
    analytics_digest = (
        hashlib.sha256(settings.ops_read_token.get_secret_value().encode()).digest()
        if settings.ops_read_token is not None
        else None
    )
    app.include_router(
        build_analytics_router(
            analytics,
            enabled=settings.product_analytics_enabled,
            token_digest=analytics_digest,
            origins=tuple(settings.allowed_origins),
            clock=clock,
        )
    )
    if settings.ops_read_token is not None:
        digest = hashlib.sha256(settings.ops_read_token.get_secret_value().encode()).digest()
        app.include_router(build_operations_router(operations, digest, telemetry))
    install_error_handlers(app)
    # Outermost first at runtime: context → CORS → origin policy → body limit → routes.
    app.add_middleware(AnalyticsBodyLimitMiddleware, max_bytes=settings.max_body_bytes)
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
    if telemetry is not None:
        from app.adapters.observability.telemetry import TelemetryMiddleware

        # FastAPI includes routers lazily; their top-level entries have no path.
        # Public route contexts enumerate the registered, effective templates.
        routes = frozenset(context.path for context in iter_route_contexts(app.routes) if context.path)
        private_digest = (
            hashlib.sha256(settings.ops_read_token.get_secret_value().encode()).digest()
            if settings.ops_read_token
            else None
        )
        app.add_middleware(
            TelemetryMiddleware, telemetry=telemetry, routes=routes, private_token_digest=private_digest
        )
    app.add_middleware(RequestContextMiddleware)
    return app
