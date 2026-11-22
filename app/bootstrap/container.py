"""Composition root: builds adapters and use cases; lifespan and HTTP assembly live beside it.

Tests patch `AsyncOpenAI`, `provider_http_client`, `build_persistence` and `GroundedComposer` on
this module, so the wiring that calls them stays here (PVA-M4.1, target-state section 4).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from openai import AsyncOpenAI

from app.adapters.catalog.knowledge import PARSER_VERSION
from app.adapters.catalog_schema import CatalogParser
from app.adapters.catalog_source import FileCatalogSource, HttpCatalogSource
from app.adapters.graph.composer import GraphAnswerComposer
from app.adapters.official_help import OfficialHelpReader
from app.adapters.postgres.database import PostgresDatabase, schema_level
from app.adapters.postgres.knowledge import PostgresKnowledgeStore
from app.adapters.postgres.product_analytics import PostgresProductAnalytics
from app.adapters.providers.fixture_provider import FixtureProvider
from app.adapters.providers.openai_embeddings import FixtureHashEmbeddings, OpenAIEmbeddings
from app.adapters.providers.openai_provider import OpenAIResponsesProvider
from app.adapters.sqlite.database import SCHEMA_LEVEL as SQLITE_SCHEMA_LEVEL
from app.ai.composer import ComposerSettings, GroundedComposer
from app.ai.prompt import PROMPT_VERSION
from app.application.catalog import CatalogService
from app.application.chat import ChatLimits, ChatService
from app.application.embedding_budget import SharedEmbeddingAccounting
from app.application.knowledge import HybridKnowledgeRetrieval
from app.application.knowledge_ports import EmbeddingAccounting
from app.application.operations import OperationsService, ServiceInfo
from app.application.product_analytics import AnalyticsService
from app.application.runs import RunRegistry
from app.application.sessions import SessionLimits, SessionService
from app.bootstrap.config import Settings, get_settings
from app.bootstrap.lifespan import MAINTENANCE_SECONDS, build_lifespan, readiness
from app.bootstrap.persistence import build_persistence
from app.bootstrap.provider_transport import close_owned_provider, provider_http_client
from app.bootstrap.routes import build_http_app
from app.bootstrap.wiring import ProviderResource, Wiring
from app.domain.budget import BudgetPolicy, Pricing, to_micro
from app.presentation.streaming import ResponseCleanups

if TYPE_CHECKING:
    from fastapi import FastAPI

    from app.adapters.observability.telemetry import RuntimeTelemetry
    from app.ai.provider import ModelProvider
    from app.application.knowledge_ports import Embeddings
    from app.application.operations import OperationsQueries
    from app.application.ports import AnswerComposer, CatalogSource, Clock
    from app.bootstrap.persistence import Persistence

__all__ = [
    "MAINTENANCE_SECONDS",
    "ProviderFactory",
    "ProviderResource",
    "SystemClock",
    "build_catalog_source",
    "build_provider",
    "create_app",
    "expected_schema_version",
]


def expected_schema_version(settings: Settings) -> str:
    """Highest migration this configuration needs, reported by /readyz (ADR-0019)."""
    if settings.application_storage == "postgres":
        return f"postgres-{schema_level(analytics=settings.product_analytics_enabled)}"
    return f"sqlite-{SQLITE_SCHEMA_LEVEL}"


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


_ProviderResource = ProviderResource  # Retain existing fixture callers and lifecycle contracts.
ProviderFactory = Callable[[Settings, EmbeddingAccounting], ProviderResource]


def build_provider(
    settings: Settings, embedding_accounting: EmbeddingAccounting | None = None
) -> _ProviderResource:
    if settings.ai_provider == "openai":
        if settings.openai_api_key is None:
            raise AssertionError
        http = provider_http_client()
        client = AsyncOpenAI(
            http_client=http,
            api_key=settings.openai_api_key.get_secret_value(),
            base_url="https://api.openai.com/v1",
            timeout=settings.openai_timeout_seconds,
            max_retries=0,
        )
        embeddings: Embeddings | None = None
        if settings.knowledge_backend == "graphrag":
            if embedding_accounting is None:
                raise AssertionError
            embeddings = OpenAIEmbeddings(client, embedding_accounting)
        return _ProviderResource(
            OpenAIResponsesProvider(
                client,
                settings.openai_model,
                settings.openai_reasoning_effort,
                settings.openai_max_retries,
            ),
            lambda: close_owned_provider(client, http),
            embeddings,
        )
    return _ProviderResource(
        FixtureProvider(chunk_delay_seconds=settings.fixture_chunk_delay_ms / 1000),
        embeddings=FixtureHashEmbeddings() if settings.knowledge_backend == "graphrag" else None,
    )


def build_catalog_source(settings: Settings) -> CatalogSource:
    hosts = frozenset(settings.catalog_allowed_hosts)
    if settings.catalog_url:
        return HttpCatalogSource(settings.catalog_url, hosts)
    return FileCatalogSource(settings.catalog_file)


def _validate_overrides(
    settings: Settings,
    provider: ModelProvider | None,
    provider_factory: ProviderFactory | None,
) -> None:
    if provider is not None and provider_factory is not None:
        raise ValueError("provider and provider_factory overrides are mutually exclusive")
    if (
        provider is not None or provider_factory is not None
    ) and settings.environment == "production":
        raise ValueError("provider overrides are for tests and fixtures only")


def _analytics_service(settings: Settings, persistence: Persistence) -> AnalyticsService | None:
    if not settings.product_analytics_enabled:
        return None
    db = persistence.database
    if isinstance(db, PostgresDatabase):
        synthetic = settings.environment != "production"
        return AnalyticsService(
            PostgresProductAnalytics(db, synthetic=synthetic),
            synthetic=synthetic,
            country_collection="trusted_proxy_header"
            if settings.product_analytics_country_enabled
            else "disabled",
        )
    raise AssertionError


def _session_service(settings: Settings, persistence: Persistence, clock: Clock) -> SessionService:
    return SessionService(
        persistence.sessions,
        persistence.messages,
        persistence.rates,
        clock,
        SessionLimits(
            retention=timedelta(hours=settings.session_retention_hours),
            bootstraps_per_hour=settings.sessions_per_client_per_hour,
            history_restore=40,
        ),
    )


def _budget(settings: Settings) -> BudgetPolicy:
    return BudgetPolicy(
        monthly_limit_micro=to_micro(settings.monthly_budget_usd),
        safety_margin=settings.budget_safety_margin,
        daily_limit_micro=to_micro(settings.daily_budget_usd),
    )


def _owned_provider(
    settings: Settings,
    accounting: EmbeddingAccounting,
    provider: ModelProvider | None,
    provider_factory: ProviderFactory | None,
) -> ProviderResource:
    if provider_factory is not None:
        return provider_factory(settings, accounting)
    if provider is not None:
        return _ProviderResource(provider)
    return build_provider(settings, accounting)


def _composer_and_knowledge(
    settings: Settings, persistence: Persistence, owned: ProviderResource, clock: Clock
) -> tuple[AnswerComposer, HybridKnowledgeRetrieval | None]:
    grounded = GroundedComposer(
        owned.provider,
        ComposerSettings(
            settings.max_output_tokens, settings.max_evidence_chars, settings.max_input_tokens
        ),
    )
    composer: AnswerComposer = grounded
    knowledge: HybridKnowledgeRetrieval | None = None
    if settings.knowledge_backend == "graphrag":
        if persistence.graph is None:
            raise AssertionError
        if not isinstance(persistence.catalog, PostgresKnowledgeStore):
            raise AssertionError
        embeddings = owned.embeddings
        if embeddings is None and settings.ai_provider == "fixture":
            embeddings = FixtureHashEmbeddings()
        if embeddings is None:
            raise AssertionError
        knowledge = HybridKnowledgeRetrieval(
            persistence.catalog, persistence.graph, embeddings, PARSER_VERSION, clock
        )
        composer = GraphAnswerComposer(grounded, knowledge, settings.max_input_tokens)
    if owned.wrap_composer is not None:
        composer = owned.wrap_composer(composer)
    return composer, knowledge


def _official_help(settings: Settings, clock: Clock) -> OfficialHelpReader | None:
    if (
        settings.official_help_enabled
        and settings.ai_provider == "openai"
        and settings.assistant_enabled
    ):
        return OfficialHelpReader(clock=clock)
    return None


def _chat_limits(settings: Settings) -> ChatLimits:
    return ChatLimits(
        enabled=settings.assistant_enabled,
        max_message_chars=settings.max_message_chars,
        history_messages=settings.history_messages,
        messages_per_session_per_day=settings.messages_per_session_per_day,
        messages_per_client_per_hour=settings.messages_per_client_per_hour,
        max_concurrent_runs=settings.max_concurrent_runs,
        run_timeout=timedelta(seconds=settings.run_timeout_seconds),
        max_input_tokens=settings.max_input_tokens,
        max_output_tokens=settings.max_output_tokens,
    )


def _chat_service(
    settings: Settings,
    persistence: Persistence,
    catalog: CatalogService,
    answering: tuple[AnswerComposer, HybridKnowledgeRetrieval | None],
    clock: Clock,
    budget: BudgetPolicy,
) -> ChatService:
    composer, knowledge = answering
    db = persistence.database
    return ChatService(
        prompt_version=PROMPT_VERSION,
        official_help=_official_help(settings, clock),
        composer=composer,
        knowledge=knowledge,
        runtime_ownership=db.runtime_ownership_alive if isinstance(db, PostgresDatabase) else None,
        catalog=catalog,
        messages=persistence.messages,
        runs=persistence.runs,
        ledger=persistence.ledger,
        metrics=persistence.metrics,
        rate_limiter=persistence.rates,
        registry=RunRegistry(),
        clock=clock,
        pricing=Pricing(
            settings.price_input_per_million,
            settings.price_cached_input_per_million,
            settings.price_cache_write_per_million,
            settings.price_output_per_million,
        ),
        budget=budget,
        limits=_chat_limits(settings),
    )


def _service_info(settings: Settings, model: str, clock: Clock) -> ServiceInfo:
    openai = settings.ai_provider == "openai"
    return ServiceInfo(
        environment=settings.environment,
        revision=settings.service_revision,
        provider=settings.ai_provider,
        model=model,
        reasoning_effort=settings.openai_reasoning_effort if openai else "n/a",
        assistant_enabled=settings.assistant_enabled,
        started_at=clock.now(),
        price_max_age_hours=settings.catalog_price_max_age_hours,
        pricing={
            "revision": settings.pricing_revision,
            "model": settings.openai_model,
            "input_per_million": str(settings.price_input_per_million),
            "cached_input_per_million": str(settings.price_cached_input_per_million),
            "cache_write_per_million": str(settings.price_cache_write_per_million),
            "output_per_million": str(settings.price_output_per_million),
        },
    )


def _telemetry(
    settings: Settings,
    clock: Clock,
    chat: ChatService,
    operations: OperationsQueries,
    ready: Callable[[], Awaitable[bool]],
) -> RuntimeTelemetry | None:
    if not settings.observability_enabled:
        return None
    from app.adapters.observability.telemetry import RuntimeTelemetry

    return RuntimeTelemetry(
        clock=clock,
        started_at=clock.now(),
        synthetic=settings.ai_provider == "fixture",
        revision=settings.service_revision,
        ready=ready,
        active_runs=lambda: len(chat.registry),
        max_runs=settings.max_concurrent_runs,
        run_window=lambda: operations.run_window(clock.now() - timedelta(hours=24)),
        endpoint=settings.telemetry_otlp_endpoint,
        sampling_ratio=settings.telemetry_trace_sampling_ratio,
        export_timeout=settings.telemetry_export_timeout_seconds,
    )


def create_app(
    settings: Settings | None = None,
    *,
    provider: ModelProvider | None = None,
    provider_factory: ProviderFactory | None = None,
    catalog_source: CatalogSource | None = None,
    clock: Clock | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    _validate_overrides(settings, provider, provider_factory)
    clock = clock or SystemClock()
    parser = CatalogParser(frozenset(settings.catalog_allowed_hosts))
    persistence = build_persistence(settings, parser)
    analytics = _analytics_service(settings, persistence)
    catalog = CatalogService(
        catalog_source or build_catalog_source(settings),
        parser,
        persistence.catalog,
        clock,
        timedelta(hours=settings.catalog_price_max_age_hours),
    )
    sessions = _session_service(settings, persistence, clock)
    budget = _budget(settings)
    accounting = SharedEmbeddingAccounting(
        persistence.ledger, clock, budget, settings.embedding_input_price_per_million
    )
    owned = _owned_provider(settings, accounting, provider, provider_factory)
    answering = _composer_and_knowledge(settings, persistence, owned, clock)
    knowledge = answering[1]
    chat = _chat_service(settings, persistence, catalog, answering, clock, budget)
    operations = OperationsService(
        persistence.operations,
        catalog,
        catalog.live,
        clock,
        budget,
        _service_info(settings, owned.provider.model, clock),
        chat.availability,
    )
    ready = readiness(persistence, chat, catalog, analytics, knowledge)
    wiring = Wiring(
        settings=settings,
        clock=clock,
        persistence=persistence,
        analytics=analytics,
        catalog=catalog,
        sessions=sessions,
        chat=chat,
        operations=operations,
        knowledge=knowledge,
        provider=owned,
        cleanups=ResponseCleanups(),
        ready=ready,
        telemetry=_telemetry(settings, clock, chat, persistence.operations, ready),
    )
    return build_http_app(wiring, build_lifespan(wiring), expected_schema_version(settings))
