"""Explicit offline-fixture composition, separate from production configuration and secrets."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import stat
import sys
from contextlib import AsyncExitStack
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from time import monotonic
from types import TracebackType
from urllib.parse import urlsplit

from app.adapters.catalog.knowledge import PARSER_VERSION, build_public_corpus
from app.adapters.catalog_schema import CatalogParser
from app.adapters.neo4j.database import Neo4jDatabase
from app.adapters.neo4j.public_graph import Neo4jPublicGraph
from app.adapters.postgres.database import PostgresDatabase
from app.adapters.postgres.knowledge import PostgresKnowledgeStore
from app.adapters.providers.openai_embeddings import FixtureHashEmbeddings
from app.application.knowledge import HybridKnowledgeRetrieval
from app.application.knowledge_evaluation import FixtureKnowledgeEvaluator
from app.domain.catalog import ActiveCatalog
from app.domain.errors import RejectedError
from app.domain.knowledge import EmbeddingPurpose, KnowledgeCorpus, ProjectionStamp
from app.domain.language import Language

ROOT = Path(__file__).resolve().parents[2]
_HOSTS = frozenset({'pequeverso.com', 'consumer.hotmart.com', 'refund.hotmart.com'})


@dataclass(frozen=True, slots=True)
class FixtureConnections:
    postgres_dsn: str = field(repr=False)
    neo4j_uri: str
    neo4j_username: str
    neo4j_password: str = field(repr=False)

    def __post_init__(self) -> None:
        pg = urlsplit(self.postgres_dsn)
        if (
            pg.scheme != 'postgresql'
            or pg.hostname != '127.0.0.1'
            or pg.port != 55440
            or pg.path != '/pv_graph_evaluation'
            or pg.query
            or pg.fragment
            or self.neo4j_uri != 'bolt://127.0.0.1:17689'
            or self.neo4j_username != 'neo4j'
            or not self.neo4j_password
        ):
            raise ValueError('only dedicated loopback fixture connections are accepted')


@dataclass(frozen=True, slots=True)
class FrozenClock:
    moment: datetime

    def now(self) -> datetime:
        return self.moment


@dataclass(frozen=True, slots=True)
class ProjectionReadiness:
    ready: bool
    attempts: int
    failures: tuple[str, ...]
    duration_seconds: float


def fixture_corpus() -> KnowledgeCorpus:
    """The snapshot export time remains explicit; it is not a new live freshness check."""
    body = (ROOT / 'catalog/catalog.v1.json').read_bytes()
    parse = CatalogParser(_HOSTS)
    catalog = parse(body)
    return build_public_corpus(body, catalog.generated_at, FixtureHashEmbeddings().spec, parse)


async def wait_for_fixture_projection(
    uri: str,
    username: str,
    password: str,
    expected: ProjectionStamp,
) -> ProjectionReadiness:
    """Bounded read-only readiness polling, never a generation retry or reindex operation.

    Cold JVM compilation can exceed the unchanged two-second transaction limit. TCP
    liveness does not prove an authenticated, complete restored projection is queryable.
    """
    if uri != 'bolt://127.0.0.1:17689':
        raise ValueError('readiness polling is restricted to the isolated fixture')
    database = Neo4jDatabase(uri, username, password)
    started = monotonic()
    failures: list[str] = []
    attempts = 0
    try:
        await database.open()
        graph = Neo4jPublicGraph(database.driver)
        while monotonic() - started < 60:
            attempts += 1
            try:
                if await graph.projection_stamp(expected.version) == expected:
                    return ProjectionReadiness(True, attempts, tuple(failures), monotonic() - started)
                failures.append('projection_missing_or_incomplete')
            except RejectedError as error:
                failures.append(error.code.value)
            await asyncio.sleep(0.5)
        return ProjectionReadiness(False, attempts, tuple(failures), monotonic() - started)
    finally:
        await database.close()


def read_fixture_connections(path: Path) -> FixtureConnections:
    if path.is_symlink():
        raise ValueError('fixture connections must be a private regular file')
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_uid != os.getuid():
        raise ValueError('fixture connections require an owner-only regular file')
    raw = json.loads(path.read_bytes())
    fields = {'postgres_dsn', 'neo4j_uri', 'neo4j_username', 'neo4j_password'}
    if not isinstance(raw, dict) or set(raw) != fields or any(not isinstance(v, str) for v in raw.values()):
        raise ValueError('fixture connection fields are invalid')
    return FixtureConnections(
        raw['postgres_dsn'], raw['neo4j_uri'], raw['neo4j_username'], raw['neo4j_password']
    )


async def evaluate_manifest(
    connections: FixtureConnections,
    manifest: Path,
    output: Path,
) -> None:
    resolved_output = await asyncio.to_thread(output.resolve)
    if resolved_output.is_relative_to(ROOT):
        raise ValueError('evaluation artifacts must remain outside the source checkout')
    raw = await asyncio.to_thread(manifest.read_bytes)
    data = json.loads(raw)
    cases = data['cases']
    corpus = await asyncio.to_thread(fixture_corpus)
    if data['catalog_sha256'] != corpus.revision.catalog_sha256 or len(cases) < 200:
        raise ValueError('evaluation requires a frozen matching catalog and at least 200 cases')
    ids = {chunk.id for chunk in corpus.chunks}
    if any(not set(case['relevant_chunk_ids']).issubset(ids) for case in cases):
        raise ValueError('relevance labels must name actual public source chunks')
    await asyncio.to_thread(output.mkdir, parents=True, exist_ok=False, mode=0o700)
    receipt: dict[str, object] = {
        'kind': 'fixture component strategy comparison, not model/API/session quality',
        'manifest_sha256': hashlib.sha256(raw).hexdigest(),
        'query_count': len(cases),
        'catalog_sha256': corpus.revision.catalog_sha256,
        'source_revision': corpus.revision.source_revision,
        'knowledge_revision': asdict(corpus.revision),
        'provider_calls': 0,
        'paid_calls': 0,
        'sent_to_model_chunk_ids': [],
        'generation_executed': False,
        'clock': 'frozen to snapshot generated_at; no claim of live price/catalog freshness',
        'vectors': 'hash64 fixture only; no semantic-quality measurement',
        'graph': 'lexical-seeded bounded graph expansion, not independent natural-language graph search',
        'labels': 'previously exposed regression and directed cases, not an independent holdout',
        'runtime_timeout_seconds': 2.0,
        'execution_code_revision': await asyncio.to_thread(_source_revision),
        'source_files_sha256': await asyncio.to_thread(_source_hashes),
    }
    try:
        async with AsyncExitStack() as cleanup:
            database = PostgresDatabase(connections.postgres_dsn, pool_size=2)
            cleanup.push_async_callback(database.close)
            graph_database = Neo4jDatabase(
                connections.neo4j_uri, connections.neo4j_username, connections.neo4j_password
            )
            cleanup.push_async_callback(graph_database.close)
            await database.open()
            await graph_database.open()
            await database.migrate()
            embeddings = FixtureHashEmbeddings()
            store = PostgresKnowledgeStore(database, CatalogParser(_HOSTS), embeddings.spec, PARSER_VERSION)
            graph = Neo4jPublicGraph(graph_database.driver)
            vectors: list[tuple[float, ...]] = []
            for start in range(0, len(corpus.chunks), 32):
                vectors.extend(
                    await embeddings.encode(
                        tuple(c.text for c in corpus.chunks[start : start + 32]), EmbeddingPurpose.INDEX
                    )
                )
            async with store.indexing_lock():
                await store.stage(corpus, tuple(vectors))
                await graph.stage(corpus)
                stamp = await graph.projection_stamp(corpus.revision.version)
                if stamp is None:
                    raise ValueError('complete graph proof is required before public activation')
                await store.mark_prepared(corpus.revision.version, stamp)
                await store.activate_prepared(corpus.revision.version)
            active = ActiveCatalog(
                CatalogParser(_HOSTS)(corpus.catalog_body),
                corpus.revision.catalog_sha256,
                corpus.verified_at,
                timedelta(days=1),
            )
            retrieval = HybridKnowledgeRetrieval(
                store, graph, embeddings, PARSER_VERSION, FrozenClock(corpus.verified_at)
            )
            evaluator = FixtureKnowledgeEvaluator(
                store, graph, embeddings, retrieval, active, corpus.revision
            )
            results = []
            for case in cases:
                language = Language.EN if case.get('language') == 'en' else Language.ES
                observation = await evaluator.evaluate(
                    case['question'], tuple(case['relevant_chunk_ids']), language
                )
                row = {'id': case['id'], **asdict(observation)}
                results.append(row)
                # Retain every completed case even if a later dependency fails.
                await asyncio.to_thread(_append_observation, output, row)
            receipt['completed_queries'] = len(results)
            receipt['status'] = 'completed'
    except BaseException as error:
        receipt['status'] = 'interrupted'
        receipt['failure_type'] = type(error).__name__
        raise
    finally:
        await asyncio.to_thread(_write_receipt, output, receipt)


def main() -> None:
    parser = argparse.ArgumentParser(description='Explicit hash-fixture retrieval comparison; no live mode')
    parser.add_argument('--fixture', action='store_true', required=True)
    parser.add_argument('--connections', required=True, type=Path)
    parser.add_argument('--manifest', type=Path, default=ROOT / 'evals/knowledge/strategies-203.v1.json')
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    asyncio.run(evaluate_manifest(read_fixture_connections(args.connections), args.manifest, args.output))


def _append_observation(output: Path, row: dict[str, object]) -> None:
    with (output / 'observations.jsonl').open('a') as target:
        target.write(json.dumps(row, ensure_ascii=False) + '\n')


def _write_receipt(output: Path, receipt: dict[str, object]) -> None:
    (output / 'receipt.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n')


def safe_exception_hook(
    kind: type[BaseException],
    _error: BaseException,
    _traceback: TracebackType | None,
) -> None:
    # The CLI preserves failure exit status while hiding driver strings, values and locals.
    print(f'Fixture evaluation failed safely ({kind.__name__}); inspect the receipt', file=sys.stderr)


def _source_revision() -> str:
    revision = os.environ.get('PV_EVALUATION_CODE_REVISION', '')
    if not re.fullmatch(r'[a-f0-9]{40}', revision):
        raise ValueError('the evaluation entry point must identify its committed source revision')
    return revision


def _source_hashes() -> dict[str, str]:
    files = (
        'app/application/knowledge.py',
        'app/application/knowledge_evaluation.py',
        'app/bootstrap/knowledge_evaluation.py',
        'app/adapters/catalog/knowledge.py',
        'app/adapters/neo4j/public_graph.py',
        'app/adapters/neo4j/database.py',
        'app/adapters/postgres/knowledge.py',
        'app/adapters/postgres/database.py',
        'app/adapters/providers/openai_embeddings.py',
        'scripts/evaluate_knowledge_strategies.py',
    )
    return {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in files}
