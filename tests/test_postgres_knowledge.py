"""Real isolated PostgreSQL/pgvector integration; never substitutes an in-memory store."""

import asyncio
import hashlib
import json
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict

from app.adapters.catalog_schema import CatalogParser
from app.adapters.postgres.database import PostgresDatabase
from app.adapters.postgres.knowledge import PostgresKnowledgeStore
from app.adapters.providers.openai_embeddings import FixtureHashEmbeddings
from app.domain.knowledge import (
    ChunkKind,
    EmbeddingPurpose,
    EmbeddingSpec,
    EntityKind,
    KnowledgeChunk,
    KnowledgeCorpus,
    KnowledgeEntity,
    KnowledgeRelation,
    KnowledgeRevision,
    RelationKind,
)
from tests.support import CATALOG_BYTES

DSN = os.environ.get('TEST_KNOWLEDGE_DSN')
pytestmark = pytest.mark.skipif(not DSN, reason='requires explicitly isolated real PG18.6/pgvector0.8.7')
PARSE = CatalogParser(frozenset({'pequeverso.com', 'consumer.hotmart.com', 'refund.hotmart.com'}))
SPEC = EmbeddingSpec('fixture', 'hash64-v1', 64)


def public_corpus(version: str = 'a') -> KnowledgeCorpus:
    catalog = PARSE(CATALOG_BYTES)
    chunks = tuple(
        KnowledgeChunk(
            f'product:{p.id}',
            ChunkKind.PRODUCT,
            p.id,
            p.name,
            p.summary,
            f'https://pequeverso.com{p.path}',
            (p.id,),
            hashlib.sha256(p.summary.encode()).hexdigest(),
            f'/products/{index}',
        )
        for index, p in enumerate(catalog.products)
    )
    return KnowledgeCorpus(
        KnowledgeRevision(
            version * 64,
            hashlib.sha256(CATALOG_BYTES).hexdigest(),
            catalog.source_revision,
            'knowledge-v1',
            SPEC,
        ),
        CATALOG_BYTES,
        datetime.now(UTC),
        chunks,
        tuple(KnowledgeEntity(c.id, EntityKind.PRODUCT, c.title, (c.id,)) for c in chunks),
        (),
    )


@asynccontextmanager
async def isolated_store() -> AsyncIterator[tuple[PostgresKnowledgeStore, PostgresDatabase]]:
    assert DSN is not None
    info = conninfo_to_dict(DSN)
    if (
        info.get('host') != '127.0.0.1'
        or info.get('port') != '55439'
        or info.get('dbname') != 'pv_knowledge_test'
    ):
        raise ValueError('test cleanup is restricted to the explicitly isolated local database')
    db = PostgresDatabase(DSN)
    await db.open()
    try:
        async with db.pool.connection() as conn:
            await conn.execute('DROP SCHEMA IF EXISTS knowledge CASCADE')
        await db.migrate()
        await db.migrate()
        yield PostgresKnowledgeStore(db, PARSE, SPEC, 'knowledge-v1'), db
    finally:
        await db.close()


async def stage(store: PostgresKnowledgeStore, corpus: KnowledgeCorpus) -> tuple[tuple[float, ...], ...]:
    vectors = await FixtureHashEmbeddings().encode(
        tuple(c.text for c in corpus.chunks), EmbeddingPurpose.INDEX
    )
    await store.stage(corpus, vectors)
    return vectors


async def prepare(store: PostgresKnowledgeStore, corpus: KnowledgeCorpus) -> None:
    stamp = await store.projection_stamp(corpus.revision.version)
    assert stamp is not None
    # The graph stamp is injected in these PG-specific tests; actual Neo4j has separate tests.
    await store.mark_prepared(corpus.revision.version, stamp)


def test_real_migrations_staging_preparation_binding_search_and_hydration() -> None:
    async def run() -> None:
        async with isolated_store() as (store, db):
            corpus = replace(public_corpus(), verified_at=datetime(2026, 10, 17, tzinfo=UTC))
            vectors = await stage(store, corpus)
            await store.stage(corpus, vectors)
            fresh_verification = corpus.verified_at + timedelta(seconds=1)
            await store.stage(replace(corpus, verified_at=fresh_verification), vectors)
            assert await store.active() is None
            with pytest.raises(ValueError, match='prepared'):
                await store.activate_prepared(corpus.revision.version)
            stamp = await store.projection_stamp(corpus.revision.version)
            assert stamp is not None and stamp.chunk_count == len(corpus.chunks)
            with pytest.raises(ValueError, match='proofs'):
                await store.mark_prepared(corpus.revision.version, replace(stamp, chunk_count=0))
            await prepare(store, corpus)
            await store.activate_prepared(corpus.revision.version)
            assert await store.active_revision() == corpus.revision
            snapshot = await store.active()
            assert snapshot is not None and snapshot.body == CATALOG_BYTES
            assert snapshot.verified_at == fresh_verification
            lexical = await store.lexical_candidates(corpus.revision.version, corpus.chunks[0].title, 4)
            assert lexical and corpus.chunks[0].id in [h.chunk_id for h in lexical]
            vector = await store.vector_candidates(corpus.revision.version, vectors[0], 2)
            assert vector[0].chunk_id == corpus.chunks[0].id
            assert (
                await store.read_chunks(corpus.revision.version, (corpus.chunks[0].id,)) == corpus.chunks[:1]
            )
            now = datetime.now(UTC)
            await store.activate(
                corpus.revision.catalog_sha256, CATALOG_BYTES, PARSE(CATALOG_BYTES), now, now
            )
            await store.mark_verified(corpus.revision.catalog_sha256, now, now)
            async with db.pool.connection() as conn:
                row = await (await conn.execute('SELECT count(*) AS n FROM knowledge.revisions')).fetchone()
                assert row is not None and row['n'] == 1

    asyncio.run(run())


def test_immutable_revision_rejects_different_vectors_and_detects_tampered_metadata() -> None:
    async def run() -> None:
        async with isolated_store() as (store, db):
            corpus = public_corpus()
            vectors = await stage(store, corpus)
            changed = tuple(-x for x in vectors[0])
            with pytest.raises(ValueError, match='immutable'):
                await store.stage(corpus, (changed, *vectors[1:]))
            async with db.pool.connection() as conn:
                await conn.execute(
                    'UPDATE knowledge.chunks SET product_ids=%s WHERE version=%s AND id=%s',
                    (['unauthorized-product'], corpus.revision.version, corpus.chunks[0].id),
                )
            with pytest.raises(ValueError, match='metadata or provenance'):
                await store.read_chunks(corpus.revision.version, (corpus.chunks[0].id,))
            async with db.pool.connection() as conn:
                await conn.execute(
                    "UPDATE knowledge.revisions SET manifest_sha256='wrong' WHERE version=%s",
                    (corpus.revision.version,),
                )
            with pytest.raises(ValueError, match='manifest hash'):
                await store.projection_stamp(corpus.revision.version)

    asyncio.run(run())


def test_index_only_vector_reuse_is_ordered_bounded_and_rejects_tampering() -> None:
    async def run() -> None:
        async with isolated_store() as (store, db):
            corpus = public_corpus()
            await stage(store, corpus)
            ids = tuple(chunk.id for chunk in reversed(corpus.chunks))
            reused = await store.vectors_for_indexing(corpus.revision.version, ids)
            assert len(reused) == len(ids)
            canonical = await store.vectors_for_indexing(
                corpus.revision.version, tuple(chunk.id for chunk in corpus.chunks)
            )
            assert reused == tuple(reversed(canonical))
            await store.stage(corpus, canonical)
            for invalid in ((), (ids[0], ids[0]), tuple(str(i) for i in range(2049))):
                with pytest.raises(ValueError, match='unique chunk ids'):
                    await store.vectors_for_indexing(corpus.revision.version, invalid)
            with pytest.raises(ValueError, match='unknown chunk'):
                await store.vectors_for_indexing(corpus.revision.version, ('unknown',))
            with pytest.raises(ValueError, match='configured identity'):
                await store.vectors_for_indexing('f' * 64, ids)
            foreign = PostgresKnowledgeStore(
                db, PARSE, EmbeddingSpec('openai', 'text-embedding-3-small', 1536), 'knowledge-v1'
            )
            with pytest.raises(ValueError, match='configured identity'):
                await foreign.vectors_for_indexing(corpus.revision.version, ids)
            async with db.pool.connection() as conn:
                await conn.execute(
                    'UPDATE knowledge.chunks SET embedding=%s::public.vector WHERE version=%s AND id=%s',
                    (json.dumps([-x for x in canonical[0]]), corpus.revision.version, corpus.chunks[0].id),
                )
            with pytest.raises(ValueError, match='integrity hash'):
                await store.vectors_for_indexing(corpus.revision.version, ids)

    asyncio.run(run())


@pytest.mark.parametrize('tamper', ['text', 'vector'])
def test_preparation_rechecks_real_rows_without_replacing_the_previous_active(tamper: str) -> None:
    async def run() -> None:
        async with isolated_store() as (store, db):
            previous, candidate = public_corpus('a'), public_corpus('b')
            await stage(store, previous)
            await prepare(store, previous)
            await store.activate_prepared(previous.revision.version)
            vectors = await stage(store, candidate)
            observed = await store.projection_stamp(candidate.revision.version)
            assert observed is not None
            async with db.pool.connection() as conn:
                if tamper == 'text':
                    await conn.execute(
                        "UPDATE knowledge.chunks SET text='Changed same-count evidence' WHERE version=%s AND id=%s",
                        (candidate.revision.version, candidate.chunks[0].id),
                    )
                else:
                    await conn.execute(
                        'UPDATE knowledge.chunks SET embedding=%s::public.vector WHERE version=%s AND id=%s',
                        (
                            json.dumps([-x for x in vectors[0]]),
                            candidate.revision.version,
                            candidate.chunks[0].id,
                        ),
                    )
            assert await store.projection_stamp(candidate.revision.version) == observed
            with pytest.raises(ValueError, match=r'hash|canonical|integrity'):
                await store.mark_prepared(candidate.revision.version, observed)
            with pytest.raises(ValueError, match='prepared'):
                await store.activate_prepared(candidate.revision.version)
            assert await store.active_revision() == previous.revision

    asyncio.run(run())


def test_cross_identity_bounds_unknown_chunks_and_nonfinite_vectors_fail_closed() -> None:
    async def run() -> None:
        async with isolated_store() as (store, db):
            corpus = public_corpus()
            vectors = await stage(store, corpus)
            await prepare(store, corpus)
            await store.activate_prepared(corpus.revision.version)
            foreign = PostgresKnowledgeStore(
                db, PARSE, EmbeddingSpec('openai', 'text-embedding-3-small', 1536), 'knowledge-v1'
            )
            with pytest.raises(ValueError, match='configured identity'):
                await foreign.active_revision()
            with pytest.raises(ValueError, match='embedding identities'):
                await foreign.vector_candidates(corpus.revision.version, (1.0,) + (0.0,) * 1535, 2)
            with pytest.raises(ValueError, match='cardinality'):
                await store.stage(corpus, ())
            with pytest.raises(ValueError, match='nonzero'):
                await store.vector_candidates(corpus.revision.version, (0.0,) * 64, 2)
            with pytest.raises(psycopg.errors.CheckViolation):
                async with db.pool.connection() as conn:
                    await conn.execute(
                        'UPDATE knowledge.chunks SET embedding=%s::public.vector', (json.dumps([0.0] * 64),)
                    )
            with pytest.raises(psycopg.errors.ForeignKeyViolation):
                async with db.pool.connection() as conn:
                    await conn.execute(
                        'UPDATE knowledge.chunks SET embedding=%s::public.vector',
                        (json.dumps([1.0] + [0.0] * 1535),),
                    )
            with pytest.raises(ValueError, match='between one and 64'):
                await store.vector_candidates(corpus.revision.version, vectors[0], 1000)
            with pytest.raises(ValueError, match='missing'):
                await store.read_chunks(corpus.revision.version, ('private:session',))
            assert await store.read_chunks(corpus.revision.version, ()) == ()

    asyncio.run(run())


def test_database_roles_forbid_runtime_projection_mutation_and_unprepared_pointer() -> None:
    async def runtime_write(db: PostgresDatabase, query: str, parameters: tuple[str, ...] = ()) -> None:
        async with db.pool.connection() as conn:
            await conn.execute('SET LOCAL ROLE pequeverso_knowledge_runtime')
            await conn.execute(query, parameters)

    async def run() -> None:
        async with isolated_store() as (store, db):
            corpus = public_corpus()
            await stage(store, corpus)
            for query in [
                'UPDATE knowledge.revisions SET prepared=true',
                "UPDATE knowledge.chunks SET text='unauthorized'",
                'DROP SCHEMA knowledge CASCADE',
            ]:
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    await runtime_write(db, query)
            with pytest.raises(psycopg.errors.ForeignKeyViolation):
                await runtime_write(
                    db, 'UPDATE knowledge.state SET active_version=%s WHERE id=1', (corpus.revision.version,)
                )
            assert await store.active() is None

    asyncio.run(run())


def test_runtime_role_binds_prepared_catalog_and_updates_activation_metadata_without_owner_rights() -> None:
    async def run() -> None:
        async with isolated_store() as (store, db):
            value = public_corpus()
            vectors = await stage(store, value)
            await prepare(store, value)
            assert DSN is not None
            runtime_db = PostgresDatabase(DSN)
            # Keep this role-scoped disposable test pool on one physical connection.
            await runtime_db.open()
            await runtime_db.pool.resize(1, 1)
            try:
                async with runtime_db.pool.connection() as conn:
                    await conn.execute('SET ROLE pequeverso_knowledge_runtime')
                runtime = PostgresKnowledgeStore(runtime_db, PARSE, SPEC, 'knowledge-v1')
                now = datetime.now(UTC)
                await runtime.activate(
                    value.revision.catalog_sha256, value.catalog_body, PARSE(value.catalog_body), now, now
                )
                await runtime.mark_verified(value.revision.catalog_sha256, now, now)
                assert await runtime.active_revision() == value.revision
                restored = await runtime.active()
                assert restored is not None and restored.body == value.catalog_body
                assert (
                    await runtime.read_chunks(value.revision.version, (value.chunks[0].id,))
                    == value.chunks[:1]
                )
                assert await runtime.vector_candidates(value.revision.version, vectors[0], 1)
                assert await runtime.lexical_candidates(value.revision.version, value.chunks[0].title, 1)
                async with runtime_db.pool.connection() as conn:
                    row = await (
                        await conn.execute(
                            'SELECT current_user AS role,activated_at,has_column_privilege(current_user,'
                            "'knowledge.state','activated_at','UPDATE') AS can_stamp FROM knowledge.state"
                        )
                    ).fetchone()
                    assert row is not None and row['role'] == 'pequeverso_knowledge_runtime'
                    assert row['can_stamp'] is True and row['activated_at'] is not None
                async with db.pool.connection() as conn:
                    row = await (
                        await conn.execute('SELECT count(*) AS n FROM knowledge.revisions')
                    ).fetchone()
                    assert row is not None and row['n'] == 1
            finally:
                await runtime_db.close()

    asyncio.run(run())


def test_failed_graph_stage_preserves_active_and_prepared_version_can_roll_back() -> None:
    async def failed_graph_stage(store: PostgresKnowledgeStore, corpus: KnowledgeCorpus) -> None:
        async with store.indexing_lock():
            await stage(store, corpus)
            raise RuntimeError('synthetic graph failure')

    async def run() -> None:
        async with isolated_store() as (store, _):
            first, second = public_corpus('a'), public_corpus('b')
            await stage(store, first)
            await prepare(store, first)
            await store.activate_prepared(first.revision.version)
            with pytest.raises(RuntimeError, match='synthetic graph failure'):
                await failed_graph_stage(store, second)
            assert await store.active_revision() == first.revision
            await prepare(store, second)
            # Two prepared revisions for one snapshot/config are ambiguous to the runtime binder.
            now = datetime.now(UTC)
            with pytest.raises(ValueError, match='unique matching'):
                await store.activate(
                    first.revision.catalog_sha256, CATALOG_BYTES, PARSE(CATALOG_BYTES), now, now
                )
            await store.activate_prepared(second.revision.version)
            await store.activate_prepared(first.revision.version)
            assert await store.active_revision() == first.revision

    asyncio.run(run())


def test_index_lock_serializes_jobs_and_cancel_releases_the_database_lock() -> None:
    async def run() -> None:
        async with isolated_store() as (store, _):
            entered = asyncio.Event()
            second = asyncio.Event()

            async def first() -> None:
                async with store.indexing_lock():
                    entered.set()
                    await asyncio.Event().wait()

            async def other() -> None:
                async with store.indexing_lock():
                    second.set()

            holder = asyncio.create_task(first())
            await asyncio.wait_for(entered.wait(), 2)
            contender = asyncio.create_task(other())
            await asyncio.sleep(0.05)
            assert not second.is_set()
            holder.cancel()
            with pytest.raises(asyncio.CancelledError):
                await holder
            await asyncio.wait_for(contender, 2)
            assert second.is_set()

    asyncio.run(run())


def test_canonical_relation_provenance_and_actual_exact_query_plan() -> None:
    async def run() -> None:
        async with isolated_store() as (store, db):
            corpus = public_corpus()
            root = corpus.entities[0]
            topic = KnowledgeEntity('topic:reading', EntityKind.TOPIC, 'Reading', root.supporting_chunk_ids)
            relation = KnowledgeRelation(
                root.id, RelationKind.HAS_TOPIC, topic.id, corpus.chunks[0].id, '/products/0/summary'
            )
            corpus = replace(corpus, entities=(*corpus.entities, topic), relations=(relation,))
            vectors = await stage(store, corpus)
            assert await store.verify_relations(corpus.revision.version, (relation,))
            assert not await store.verify_relations(
                corpus.revision.version, (replace(relation, source_pointer='/private/orders'),)
            )
            async with db.pool.connection() as conn:
                row = await (
                    await conn.execute(
                        'EXPLAIN (ANALYZE,BUFFERS,FORMAT JSON) SELECT id FROM knowledge.chunks WHERE version=%s'
                        ' ORDER BY embedding <=> %s::public.vector,id LIMIT 2',
                        (corpus.revision.version, json.dumps(vectors[0])),
                    )
                ).fetchone()
            assert row is not None
            plan = row['QUERY PLAN']
            assert plan[0]['Plan']['Node Type'] == 'Limit'
            assert plan[0]['Plan']['Actual Rows'] <= 2
            output = os.environ.get('KNOWLEDGE_PLAN_OUTPUT')
            if output:
                await asyncio.to_thread(Path(output).write_text, json.dumps(plan, indent=2) + '\n')

    asyncio.run(run())
