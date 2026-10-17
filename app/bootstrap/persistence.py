"""Construct explicitly named persistence adapters; startup owns every resource."""

from __future__ import annotations

from dataclasses import dataclass

from app.adapters.catalog.knowledge import PARSER_VERSION
from app.adapters.catalog_schema import CatalogParser
from app.adapters.neo4j.database import Neo4jDatabase
from app.adapters.neo4j.public_graph import Neo4jPublicGraph
from app.adapters.postgres.database import PostgresDatabase
from app.adapters.postgres.knowledge import PostgresKnowledgeStore
from app.adapters.postgres.private_ledger import PostgresLedger, PostgresRateLimiter
from app.adapters.postgres.private_operations import PostgresOperationsQueries, PostgresRunMetrics
from app.adapters.postgres.private_stores import (
    PostgresMessageStore,
    PostgresRunStore,
    PostgresSessionStore,
)
from app.adapters.sqlite.catalog_repository import SqliteCatalogRepository
from app.adapters.sqlite.database import Database
from app.adapters.sqlite.ledger import SqliteLedger, SqliteRateLimiter
from app.adapters.sqlite.operations import SqliteOperationsQueries, SqliteRunMetrics
from app.adapters.sqlite.stores import SqliteMessageStore, SqliteRunStore, SqliteSessionStore
from app.application.operations import OperationsQueries
from app.application.ports import CatalogRepository, MessageStore, RunStore, SessionStore
from app.bootstrap.config import Settings
from app.domain.knowledge import EmbeddingSpec


@dataclass(frozen=True, slots=True)
class Persistence:
    database: Database | PostgresDatabase
    resources: tuple[Database | PostgresDatabase | Neo4jDatabase, ...]
    sessions: SessionStore
    messages: MessageStore
    runs: RunStore
    ledger: SqliteLedger | PostgresLedger
    rates: SqliteRateLimiter | PostgresRateLimiter
    metrics: SqliteRunMetrics | PostgresRunMetrics
    operations: OperationsQueries
    catalog: CatalogRepository
    public_database: PostgresDatabase | None = None
    graph: Neo4jPublicGraph | None = None


def build_persistence(settings: Settings, parser: CatalogParser) -> Persistence:
    if settings.application_storage == 'sqlite':
        database = Database(settings.database_path)
        return Persistence(
            database=database,
            resources=(database,),
            sessions=SqliteSessionStore(database),
            messages=SqliteMessageStore(database),
            runs=SqliteRunStore(database),
            ledger=SqliteLedger(database),
            rates=SqliteRateLimiter(database),
            metrics=SqliteRunMetrics(database),
            operations=SqliteOperationsQueries(database),
            catalog=SqliteCatalogRepository(database),
        )
    assert settings.postgres_private_dsn is not None
    assert settings.postgres_knowledge_dsn is not None
    assert settings.neo4j_uri is not None
    assert settings.neo4j_password is not None
    private = PostgresDatabase(
        settings.postgres_private_dsn.get_secret_value(), pool_size=settings.postgres_private_pool_size
    )
    public = PostgresDatabase(
        settings.postgres_knowledge_dsn.get_secret_value(), pool_size=settings.postgres_knowledge_pool_size
    )
    graph_database = Neo4jDatabase(
        settings.neo4j_uri, settings.neo4j_username, settings.neo4j_password.get_secret_value()
    )
    spec = (
        EmbeddingSpec('openai', 'text-embedding-3-small', 1536)
        if settings.ai_provider == 'openai'
        else EmbeddingSpec('fixture', 'hash64-v1', 64)
    )
    return Persistence(
        database=private,
        resources=(private, public, graph_database),
        sessions=PostgresSessionStore(private),
        messages=PostgresMessageStore(private),
        runs=PostgresRunStore(private),
        ledger=PostgresLedger(private),
        rates=PostgresRateLimiter(private),
        metrics=PostgresRunMetrics(private),
        operations=PostgresOperationsQueries(private, public),
        catalog=PostgresKnowledgeStore(public, parser, spec, PARSER_VERSION),
        public_database=public,
        graph=Neo4jPublicGraph(graph_database.driver),
    )
