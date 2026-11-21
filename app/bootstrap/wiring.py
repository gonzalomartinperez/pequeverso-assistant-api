"""The wired object graph that the lifespan and the HTTP assembly share (PVA-M4.1)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from app.adapters.observability.telemetry import RuntimeTelemetry
    from app.ai.provider import ModelProvider
    from app.application.catalog import CatalogService
    from app.application.chat import ChatService
    from app.application.knowledge import HybridKnowledgeRetrieval
    from app.application.knowledge_ports import Embeddings
    from app.application.operations import OperationsService
    from app.application.ports import AnswerComposer, Clock
    from app.application.product_analytics import AnalyticsService
    from app.application.sessions import SessionService
    from app.bootstrap.config import Settings
    from app.bootstrap.persistence import Persistence
    from app.presentation.streaming import ResponseCleanups


@dataclass(frozen=True, slots=True)
class ProviderResource:
    """Only composition owns the client cleanup; use cases receive the provider port."""

    provider: ModelProvider
    close: Callable[[], Awaitable[None]] | None = None
    embeddings: Embeddings | None = None
    wrap_composer: Callable[[AnswerComposer], AnswerComposer] | None = None


@dataclass(frozen=True, slots=True)
class Wiring:
    """Every wired service, built once per application by `create_app` (target-state section 4)."""

    settings: Settings
    clock: Clock
    persistence: Persistence
    analytics: AnalyticsService | None
    catalog: CatalogService
    sessions: SessionService
    chat: ChatService
    operations: OperationsService
    knowledge: HybridKnowledgeRetrieval | None
    provider: ProviderResource
    cleanups: ResponseCleanups
    ready: Callable[[], Awaitable[bool]]
    telemetry: RuntimeTelemetry | None
