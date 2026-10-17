"""Explicit isolated evaluation composition; no keys, paid flags or live CLI bypass here.

The caller supplies a bounded embeddings factory through ports. Production HTTP startup
never calls these jobs, and migrations/LOGIN provisioning remain explicit operator steps.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import AsyncExitStack
from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Any

from pydantic import SecretStr

from app.adapters.catalog.knowledge import PARSER_VERSION, build_public_corpus
from app.adapters.catalog_schema import CatalogParser
from app.adapters.graph.composer import GraphPrepared
from app.adapters.neo4j.database import Neo4jDatabase
from app.adapters.neo4j.public_graph import Neo4jPublicGraph
from app.adapters.postgres.database import PostgresDatabase
from app.adapters.postgres.knowledge import PostgresKnowledgeStore
from app.adapters.postgres.private_ledger import PostgresLedger
from app.adapters.postgres.private_operations import PostgresOperationsQueries
from app.application.embedding_budget import SharedEmbeddingAccounting
from app.application.indexing import IndexResult, KnowledgeIndexer
from app.application.knowledge_ports import EmbeddingAccounting, Embeddings
from app.application.ports import AnswerComposer, Clock, ComposerEvent, PreparedTurn, Turn
from app.domain.budget import BudgetPolicy, to_micro


@dataclass(frozen=True, slots=True)
class EvaluationIndexConfig:
    indexer_dsn: SecretStr
    accounting_dsn: SecretStr
    neo4j_uri: str
    neo4j_username: str
    neo4j_password: SecretStr


@dataclass(frozen=True, slots=True)
class EmbeddingResource:
    embeddings: Embeddings
    close: Callable[[], Awaitable[None]] | None = None


EmbeddingFactory = Callable[[EmbeddingAccounting], EmbeddingResource]


class RecordingComposer:
    """Observe public retrieval separately from passages actually sent to generation.

    This stores no question, history or instructions and changes no prepared state.
    """

    def __init__(self, composer: AnswerComposer, records: list[dict[str, Any]]) -> None:
        self._composer = composer
        self._records = records

    @property
    def model(self) -> str:
        return self._composer.model

    def prepare(self, turn: Turn) -> PreparedTurn:
        return self._composer.prepare(turn)

    async def compose(self, prepared: PreparedTurn) -> AsyncGenerator[ComposerEvent]:
        stream = self._composer.compose(prepared)
        try:
            async for event in stream:
                yield event
        finally:
            try:
                await stream.aclose()
            finally:
                if isinstance(prepared, GraphPrepared):
                    self._records.append(
                        {
                            'retrieved': asdict(prepared.retrieval) if prepared.retrieval else None,
                            'sent_chunk_ids': list(prepared.sent_chunk_ids),
                            'catalog_only': bool(getattr(prepared, 'catalog_only', False)),
                            'generation_started': prepared.generation_started,
                        }
                    )


async def index_evaluation_snapshot(
    config: EvaluationIndexConfig, body: bytes, clock: Clock, factory: EmbeddingFactory
) -> IndexResult:
    parser = CatalogParser(frozenset({'pequeverso.com', 'consumer.hotmart.com', 'refund.hotmart.com'}))
    # Parse the pinned public snapshot before acquiring any resource or constructing a client.
    catalog = parser(body)
    async with AsyncExitStack() as resources:
        public = PostgresDatabase(config.indexer_dsn.get_secret_value(), pool_size=2)
        accounting_db = PostgresDatabase(config.accounting_dsn.get_secret_value(), pool_size=2)
        neo = Neo4jDatabase(config.neo4j_uri, config.neo4j_username, config.neo4j_password.get_secret_value())
        for database in (public, accounting_db, neo):
            resources.push_async_callback(database.close)
            await database.open()
        ledger = PostgresLedger(accounting_db)
        accounting = SharedEmbeddingAccounting(
            ledger,
            clock,
            BudgetPolicy(to_micro(Decimal(10)), Decimal('0.1'), to_micro(Decimal(1))),
            Decimal('0.02'),
        )
        owned = factory(accounting)
        if owned.close is not None:
            resources.push_async_callback(owned.close)
        corpus = build_public_corpus(
            body, min(clock.now(), catalog.generated_at), owned.embeddings.spec, parser
        )
        indexer = KnowledgeIndexer(
            PostgresKnowledgeStore(public, parser, owned.embeddings.spec, PARSER_VERSION),
            Neo4jPublicGraph(neo.driver),
            owned.embeddings,
            ledger.abandon_index_pending,
        )
        return await indexer.index(corpus)


async def evaluation_spend_snapshot(
    private_dsn: SecretStr, public_dsn: SecretStr, clock: Clock
) -> list[dict[str, int | str]]:
    """Read aggregate application accounting through its adapter, never ad-hoc evaluator SQL."""
    async with AsyncExitStack() as resources:
        private = PostgresDatabase(private_dsn.get_secret_value(), pool_size=2)
        public = PostgresDatabase(public_dsn.get_secret_value(), pool_size=2)
        for database in (private, public):
            resources.push_async_callback(database.close)
            await database.open()
        queries = PostgresOperationsQueries(private, public)
        now = clock.now()
        return [
            {'period': period, **asdict(await queries.spend(period, now.strftime(pattern)))}
            for period, pattern in (('month', '%Y-%m'), ('day', '%Y-%m-%d'))
        ]
