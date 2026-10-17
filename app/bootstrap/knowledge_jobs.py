"""Explicit operator jobs; no migration or indexing is performed by HTTP startup."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import hashlib
import json
import os
import sys
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path

from openai import AsyncOpenAI
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.adapters.catalog.knowledge import PARSER_VERSION, build_public_corpus
from app.adapters.catalog_schema import CatalogParser
from app.adapters.neo4j.database import Neo4jDatabase
from app.adapters.neo4j.public_graph import Neo4jPublicGraph
from app.adapters.openai_embeddings import FixtureHashEmbeddings, OpenAIEmbeddings
from app.adapters.postgres.database import PostgresDatabase
from app.adapters.postgres.knowledge import PostgresKnowledgeStore
from app.adapters.postgres.private_ledger import PostgresLedger
from app.application.embedding_budget import SharedEmbeddingAccounting
from app.application.indexing import KnowledgeIndexer
from app.application.knowledge_ports import Embeddings
from app.bootstrap.container import SystemClock
from app.bootstrap.logging import configure_logging
from app.domain.budget import BudgetPolicy, to_micro
from app.domain.knowledge import MAX_PUBLIC_BODY_BYTES


class IndexSettings(BaseSettings):
    """Offline capabilities are separate from both public and private runtime credentials."""

    model_config = SettingsConfigDict(env_file=None, extra='ignore')
    postgres_indexer_dsn: SecretStr
    postgres_embedding_dsn: SecretStr
    neo4j_uri: str
    neo4j_username: str = 'neo4j'
    neo4j_password: SecretStr
    ai_provider: str = 'fixture'
    allow_paid_ai: bool = False
    openai_api_key: SecretStr | None = None
    monthly_budget_usd: Decimal = Field(default=Decimal(10), gt=0, le=10)
    daily_budget_usd: Decimal = Field(default=Decimal(1), gt=0, le=1)
    embedding_input_price_per_million: Decimal = Field(default=Decimal('0.02'), gt=0)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catalog', type=Path, required=True)
    parser.add_argument('--expected-catalog-sha256', required=True)
    parser.add_argument('--receipt', type=Path, required=True)
    parser.add_argument('--allow-paid-indexing', action='store_true')
    return parser


async def index_main() -> int:
    configure_logging()
    args = _parser().parse_args()
    descriptor: int | None = None
    try:
        settings = IndexSettings()
        if settings.ai_provider not in {'fixture', 'openai'}:
            raise ValueError('only explicit fixture or OpenAI embeddings are supported')
        if settings.ai_provider == 'openai' and not (
            args.allow_paid_indexing and settings.allow_paid_ai and settings.openai_api_key
        ):
            raise ValueError('paid indexing requires explicit authorization, configuration and private key')
        if settings.daily_budget_usd > settings.monthly_budget_usd:
            raise ValueError('daily budget exceeds monthly budget')
        with args.catalog.open('rb') as source:
            body = source.read(MAX_PUBLIC_BODY_BYTES + 1)
        if (
            len(body) > MAX_PUBLIC_BODY_BYTES
            or hashlib.sha256(body).hexdigest() != args.expected_catalog_sha256
        ):
            raise ValueError('catalog size or pinned digest mismatch')
        parser = CatalogParser(frozenset({'pequeverso.com', 'consumer.hotmart.com', 'refund.hotmart.com'}))
        catalog = parser(body)
        # Refuse receipt collisions before opening any network connection or charging a request.
        descriptor = os.open(args.receipt, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, 'w') as receipt:
            descriptor = None
            receipt.write('{"status":"started","cost_status":"not_yet_known"}\n')
            receipt.flush()
            async with contextlib.AsyncExitStack() as resources:
                public = PostgresDatabase(settings.postgres_indexer_dsn.get_secret_value(), pool_size=2)
                accounting_db = PostgresDatabase(
                    settings.postgres_embedding_dsn.get_secret_value(), pool_size=2
                )
                neo = Neo4jDatabase(
                    settings.neo4j_uri, settings.neo4j_username, settings.neo4j_password.get_secret_value()
                )
                for database in (public, accounting_db, neo):
                    resources.push_async_callback(database.close)
                    await database.open()
                clock = SystemClock()
                ledger = PostgresLedger(accounting_db)
                policy = BudgetPolicy(
                    to_micro(settings.monthly_budget_usd),
                    Decimal('0.10'),
                    to_micro(settings.daily_budget_usd),
                )
                embeddings: Embeddings = FixtureHashEmbeddings()
                if settings.ai_provider == 'openai':
                    assert settings.openai_api_key is not None
                    client = AsyncOpenAI(
                        api_key=settings.openai_api_key.get_secret_value(),
                        base_url='https://api.openai.com/v1',
                        max_retries=0,
                        timeout=10,
                    )
                    resources.push_async_callback(client.close)
                    embeddings = OpenAIEmbeddings(
                        client,
                        SharedEmbeddingAccounting(
                            ledger, clock, policy, settings.embedding_input_price_per_million
                        ),
                    )
                verified_at = min(clock.now(), catalog.generated_at)
                corpus = build_public_corpus(body, verified_at, embeddings.spec, parser)
                indexer = KnowledgeIndexer(
                    PostgresKnowledgeStore(public, parser, embeddings.spec, PARSER_VERSION),
                    Neo4jPublicGraph(neo.driver),
                    embeddings,
                    ledger.abandon_index_pending,
                )
                result = await indexer.index(corpus)
                output = {
                    'status': 'verified',
                    'provider': settings.ai_provider,
                    'embedding': asdict(embeddings.spec),
                    'catalog_sha256': corpus.revision.catalog_sha256,
                    'source_revision': corpus.revision.source_revision,
                    'result': asdict(result),
                }
                receipt.seek(0)
                receipt.write(json.dumps(output, indent=2) + '\n')
                receipt.truncate()
        print('Public projections verified and activated; content-free private receipt written.')
        return 0
    except Exception as error:  # noqa: BLE001 - never print private connection details or SDK responses
        print(
            f'Indexing failed ({type(error).__name__}); inspect the private receipt and ledger before retrying.'
        )
        return 1
    finally:
        if descriptor is not None:
            os.close(descriptor)


async def migrate_main() -> int:
    """Explicit privileged SQL job. vps-ops provisions LOGIN identities separately."""
    configure_logging()
    dsn = os.environ.get('POSTGRES_MIGRATION_DSN')
    if not dsn:
        print('POSTGRES_MIGRATION_DSN is required; no credentials are accepted in arguments.')
        return 2
    db = PostgresDatabase(dsn, pool_size=2)
    try:
        await db.open()
        await db.migrate()
        print('Project PostgreSQL migrations completed; LOGIN identities remain an operator responsibility.')
        return 0
    except Exception as error:  # noqa: BLE001 - SQL details can contain private data
        print(f'Migration failed ({type(error).__name__}); inspect private state before retrying.')
        return 1
    finally:
        await db.close()


def main() -> int:
    """Image entry point: python -m app.bootstrap.knowledge_jobs index|migrate."""
    if len(sys.argv) < 2 or sys.argv[1] not in {'index', 'migrate'}:
        print('Usage: python -m app.bootstrap.knowledge_jobs index|migrate [options]')
        return 2
    action = sys.argv.pop(1)
    if action == 'migrate' and len(sys.argv) != 1:
        print('Migration accepts no arguments; provide the private migration identity via environment.')
        return 2
    return asyncio.run(index_main() if action == 'index' else migrate_main())


if __name__ == '__main__':
    raise SystemExit(main())
