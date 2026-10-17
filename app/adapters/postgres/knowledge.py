"""Immutable, prepared public projections. PostgreSQL owns the sole active pointer.

The borrowed pool is closed by bootstrap. Every query is fixed/parameterized and bounded;
runtime binding cannot create embeddings or select an arbitrary latest version.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import datetime
from typing import Any

from psycopg.types.json import Jsonb

from app.adapters.postgres.database import PostgresDatabase, Row
from app.application.ports import CatalogParser, StoredSnapshot
from app.domain.catalog import Catalog
from app.domain.knowledge import (
    ChunkKind,
    EmbeddingSpec,
    KnowledgeChunk,
    KnowledgeCorpus,
    KnowledgeHit,
    KnowledgeRelation,
    KnowledgeRevision,
    ProjectionStamp,
    RetrievalStrategy,
    validate_vector,
)

MAX_RETRIEVAL_LIMIT = 64


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _manifest(corpus: KnowledgeCorpus) -> dict[str, Any]:
    return {
        'revision': asdict(corpus.revision),
        'chunks': [asdict(chunk) for chunk in corpus.chunks],
        'entities': [asdict(entity) for entity in corpus.entities],
        'relations': [asdict(relation) for relation in corpus.relations],
    }


def _revision(row: Row) -> KnowledgeRevision:
    return KnowledgeRevision(
        row['version'],
        row['catalog_sha256'],
        row['source_revision'],
        row['parser_version'],
        EmbeddingSpec(row['embedding_provider'], row['embedding_model'], row['embedding_dimensions']),
    )


def _chunk(row: Row) -> KnowledgeChunk:
    return KnowledgeChunk(
        row['id'],
        ChunkKind(row['kind']),
        row['source_id'],
        row['title'],
        row['text'],
        row['url'],
        tuple(row['product_ids']),
        row['sha256'],
        row['source_pointer'],
    )


def _limit(limit: int) -> None:
    if type(limit) is not int or not 1 <= limit <= MAX_RETRIEVAL_LIMIT:
        raise ValueError('retrieval limit must be between one and 64')


class PostgresKnowledgeStore:
    def __init__(
        self,
        database: PostgresDatabase,
        parse: CatalogParser,
        embedding: EmbeddingSpec,
        parser_version: str,
    ) -> None:
        if not parser_version:
            raise ValueError('a configured parser identity is required')
        self._db = database
        self._parse = parse
        self._embedding = embedding
        self._parser_version = parser_version

    def _matches(self, revision: KnowledgeRevision) -> bool:
        return revision.embedding == self._embedding and revision.parser_version == self._parser_version

    @asynccontextmanager
    async def indexing_lock(self) -> AsyncIterator[None]:
        # A session lock spans provider/graph I/O without keeping an idle SQL transaction.
        # Closing this dedicated connection releases it even on cancellation/graph failure.
        async with self._db.pool.connection() as connection:
            try:
                await connection.set_autocommit(True)
                await connection.execute('SELECT pg_advisory_lock(684721024)')
                yield
            finally:
                await connection.close()

    async def stage(self, corpus: KnowledgeCorpus, vectors: tuple[tuple[float, ...], ...]) -> None:
        if not self._matches(corpus.revision) or len(vectors) != len(corpus.chunks):
            raise ValueError('projection identity or vector cardinality mismatch')
        for vector in vectors:
            validate_vector(vector, corpus.revision.embedding)
        # Re-parse authorized catalog bytes before persistence, never a free-form knowledge source.
        catalog = self._parse(corpus.catalog_body)
        if catalog.source_revision != corpus.revision.source_revision:
            raise ValueError('corpus source revision does not match the validated catalog')
        manifest = _manifest(corpus)
        manifest_hash = hashlib.sha256(_json(manifest).encode()).hexdigest()
        vector_hash = hashlib.sha256(_json(vectors).encode()).hexdigest()
        revision = corpus.revision
        async with self._db.pool.connection() as connection:
            inserted = await connection.execute(
                'INSERT INTO knowledge.revisions(version,catalog_sha256,source_revision,parser_version,'
                'embedding_provider,embedding_model,embedding_dimensions,catalog_body,manifest,'
                'manifest_sha256,vector_sha256,verified_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)'
                ' ON CONFLICT(version) DO NOTHING RETURNING version',
                (
                    revision.version,
                    revision.catalog_sha256,
                    revision.source_revision,
                    revision.parser_version,
                    revision.embedding.provider,
                    revision.embedding.model,
                    revision.embedding.dimensions,
                    corpus.catalog_body,
                    Jsonb(manifest),
                    manifest_hash,
                    vector_hash,
                    corpus.verified_at,
                ),
            )
            if await inserted.fetchone() is None:
                existing = await (
                    await connection.execute(
                        'SELECT manifest_sha256,vector_sha256 FROM knowledge.revisions WHERE version=%s',
                        (revision.version,),
                    )
                ).fetchone()
                if (
                    existing is None
                    or existing['manifest_sha256'] != manifest_hash
                    or existing['vector_sha256'] != vector_hash
                ):
                    raise ValueError('immutable knowledge revision cannot be overwritten')
                # Freshness is verification metadata, not an immutable public fact/vector.
                await connection.execute(
                    'UPDATE knowledge.revisions SET verified_at=GREATEST(verified_at,%s) WHERE version=%s',
                    (corpus.verified_at, revision.version),
                )
                return
            async with connection.cursor() as cursor:
                await cursor.executemany(
                    'INSERT INTO knowledge.chunks(version,id,kind,source_id,title,text,url,product_ids,'
                    'sha256,source_pointer,embedding) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::public.vector)',
                    [
                        (
                            revision.version,
                            c.id,
                            c.kind.value,
                            c.source_id,
                            c.title,
                            c.text,
                            c.url,
                            list(c.product_ids),
                            c.sha256,
                            c.source_pointer,
                            _json(v),
                        )
                        for c, v in zip(corpus.chunks, vectors, strict=True)
                    ],
                )

    async def projection_stamp(self, version: str) -> ProjectionStamp | None:
        async with self._db.pool.connection() as connection:
            row = await (
                await connection.execute(
                    'SELECT r.version,r.catalog_sha256,r.manifest,r.manifest_sha256,count(c.id) AS chunk_count'
                    ' FROM knowledge.revisions r LEFT JOIN knowledge.chunks c ON c.version=r.version'
                    ' WHERE r.version=%s GROUP BY r.version',
                    (version,),
                )
            ).fetchone()
        if row is None:
            return None
        manifest = row['manifest']
        if hashlib.sha256(_json(manifest).encode()).hexdigest() != row['manifest_sha256']:
            raise ValueError('stored canonical manifest hash mismatch')
        if row['chunk_count'] != len(manifest['chunks']):
            raise ValueError('stored projection is incomplete')
        return ProjectionStamp(
            version,
            row['catalog_sha256'],
            row['chunk_count'],
            len(manifest['entities']),
            len(manifest['relations']),
        )

    async def mark_prepared(self, version: str, graph_stamp: ProjectionStamp) -> None:
        observed = await self.projection_stamp(version)
        if observed is None or observed != graph_stamp:
            raise ValueError('graph and PostgreSQL projection proofs do not match')
        async with self._db.pool.connection() as connection:
            await connection.execute(
                'UPDATE knowledge.revisions SET prepared=true WHERE version=%s', (version,)
            )

    async def activate_prepared(self, version: str) -> None:
        async with self._db.pool.connection() as connection:
            row = await (
                await connection.execute(
                    'SELECT * FROM knowledge.revisions WHERE version=%s AND prepared FOR SHARE',
                    (version,),
                )
            ).fetchone()
            if row is None or not self._matches(_revision(row)):
                raise ValueError('only matching prepared knowledge may become active')
            await connection.execute(
                'UPDATE knowledge.state SET active_version=%s,verified_at=%s,last_attempt_at=%s,'
                'last_failure=NULL WHERE id=1',
                (version, row['verified_at'], row['verified_at']),
            )

    async def active_revision(self) -> KnowledgeRevision | None:
        async with self._db.pool.connection() as connection:
            row = await (
                await connection.execute(
                    'SELECT r.* FROM knowledge.revisions r JOIN knowledge.state s ON s.active_version=r.version'
                    ' WHERE s.id=1 AND r.prepared',
                )
            ).fetchone()
        if row is None:
            return None
        revision = _revision(row)
        if not self._matches(revision):
            raise ValueError('active knowledge does not match configured identity')
        return revision

    async def active(self) -> StoredSnapshot | None:
        async with self._db.pool.connection() as connection:
            row = await (
                await connection.execute(
                    'SELECT r.*,s.verified_at AS active_verified_at FROM knowledge.revisions r'
                    ' JOIN knowledge.state s ON s.active_version=r.version WHERE s.id=1 AND r.prepared',
                )
            ).fetchone()
        if row is None:
            return None
        if not self._matches(_revision(row)):
            raise ValueError('active knowledge does not match configured identity')
        body = bytes(row['catalog_body'])
        if hashlib.sha256(body).hexdigest() != row['catalog_sha256']:
            raise ValueError('stored catalog hash mismatch')
        return StoredSnapshot(row['catalog_sha256'], body, row['active_verified_at'])

    async def activate(
        self,
        sha256: str,
        body: bytes,
        catalog: Catalog,
        verified_at: datetime,
        attempted_at: datetime,
    ) -> None:
        if hashlib.sha256(body).hexdigest() != sha256 or self._parse(body) != catalog:
            raise ValueError('catalog binding requires matching validated snapshot bytes')
        async with self._db.pool.connection() as connection:
            rows = await (
                await connection.execute(
                    'SELECT version FROM knowledge.revisions WHERE catalog_sha256=%s AND catalog_body=%s'
                    ' AND parser_version=%s AND embedding_provider=%s AND embedding_model=%s'
                    ' AND embedding_dimensions=%s AND prepared LIMIT 2',
                    (
                        sha256,
                        body,
                        self._parser_version,
                        self._embedding.provider,
                        self._embedding.model,
                        self._embedding.dimensions,
                    ),
                )
            ).fetchall()
            if len(rows) != 1:
                raise ValueError('catalog binding needs one unique matching prepared revision')
            await connection.execute(
                'UPDATE knowledge.state SET active_version=%s,verified_at=%s,last_attempt_at=%s,'
                'last_failure=NULL WHERE id=1',
                (rows[0]['version'], verified_at, attempted_at),
            )

    async def mark_verified(self, sha256: str, verified_at: datetime, attempted_at: datetime) -> None:
        async with self._db.pool.connection() as connection:
            cursor = await connection.execute(
                'UPDATE knowledge.state s SET verified_at=%s,last_attempt_at=%s,last_failure=NULL'
                ' FROM knowledge.revisions r WHERE s.id=1 AND s.active_version=r.version'
                ' AND r.catalog_sha256=%s AND r.parser_version=%s AND r.embedding_provider=%s'
                ' AND r.embedding_model=%s AND r.embedding_dimensions=%s AND r.prepared',
                (
                    verified_at,
                    attempted_at,
                    sha256,
                    self._parser_version,
                    self._embedding.provider,
                    self._embedding.model,
                    self._embedding.dimensions,
                ),
            )
            if cursor.rowcount != 1:
                raise ValueError('verification cannot refresh a foreign or absent active revision')

    async def record_failure(self, reason: str, now: datetime) -> None:
        # Only exception class names are retained, never arbitrary messages/DSNs/request text.
        safe = reason if reason.isidentifier() and len(reason) <= 80 else 'KnowledgeSyncFailure'
        async with self._db.pool.connection() as connection:
            await connection.execute(
                'UPDATE knowledge.state SET last_failure=%s,last_attempt_at=%s,last_failure_at=%s WHERE id=1',
                (safe, now, now),
            )

    async def lexical_candidates(self, version: str, question: str, limit: int) -> tuple[KnowledgeHit, ...]:
        _limit(limit)
        if not question.strip() or len(question.encode()) > 8000:
            return ()
        async with self._db.pool.connection() as connection:
            rows = await (
                await connection.execute(
                    "SELECT id,sha256,ts_rank_cd(search,websearch_to_tsquery('simple',%s)) AS score"
                    " FROM knowledge.chunks WHERE version=%s AND search @@ websearch_to_tsquery('simple',%s)"
                    ' ORDER BY score DESC,id LIMIT %s',
                    (question, version, question, limit),
                )
            ).fetchall()
        return tuple(
            KnowledgeHit(version, r['id'], r['sha256'], float(r['score']), RetrievalStrategy.LEXICAL)
            for r in rows
        )

    async def vector_candidates(
        self,
        version: str,
        vector: tuple[float, ...],
        limit: int,
    ) -> tuple[KnowledgeHit, ...]:
        _limit(limit)
        validate_vector(vector, self._embedding)
        async with self._db.pool.connection() as connection:
            row = await (
                await connection.execute(
                    'SELECT * FROM knowledge.revisions WHERE version=%s',
                    (version,),
                )
            ).fetchone()
            if row is None or not self._matches(_revision(row)):
                raise ValueError('vector search cannot cross embedding identities')
            rows = await (
                await connection.execute(
                    'SELECT id,sha256,1-(embedding <=> %s::public.vector) AS score'
                    ' FROM knowledge.chunks WHERE version=%s ORDER BY embedding <=> %s::public.vector,id LIMIT %s',
                    (_json(vector), version, _json(vector), limit),
                )
            ).fetchall()
        return tuple(
            KnowledgeHit(version, r['id'], r['sha256'], float(r['score']), RetrievalStrategy.VECTOR)
            for r in rows
            if math.isfinite(float(r['score']))
        )

    async def read_chunks(self, version: str, ids: tuple[str, ...]) -> tuple[KnowledgeChunk, ...]:
        if len(ids) > MAX_RETRIEVAL_LIMIT or len(ids) != len(set(ids)):
            raise ValueError('chunk hydration must be bounded and unique')
        if not ids:
            return ()
        async with self._db.pool.connection() as connection:
            manifest_row = await (
                await connection.execute(
                    'SELECT manifest,manifest_sha256 FROM knowledge.revisions WHERE version=%s',
                    (version,),
                )
            ).fetchone()
            rows = await (
                await connection.execute(
                    'SELECT * FROM knowledge.chunks WHERE version=%s AND id=ANY(%s)',
                    (version, list(ids)),
                )
            ).fetchall()
        if manifest_row is None:
            raise ValueError('requested knowledge revision is missing')
        manifest = manifest_row['manifest']
        if hashlib.sha256(_json(manifest).encode()).hexdigest() != manifest_row['manifest_sha256']:
            raise ValueError('stored canonical manifest hash mismatch')
        canonical = {chunk['id']: _json(chunk) for chunk in manifest['chunks']}
        by_id = {row['id']: _chunk(row) for row in rows}
        if len(by_id) != len(ids):
            raise ValueError('requested knowledge chunk is missing')
        if any(_json(asdict(chunk)) != canonical.get(chunk.id) for chunk in by_id.values()):
            raise ValueError('stored chunk metadata or provenance does not match canonical manifest')
        return tuple(by_id[id_] for id_ in ids)

    async def verify_relations(self, version: str, relations: tuple[KnowledgeRelation, ...]) -> bool:
        if len(relations) > MAX_RETRIEVAL_LIMIT:
            return False
        async with self._db.pool.connection() as connection:
            row = await (
                await connection.execute(
                    'SELECT manifest,manifest_sha256 FROM knowledge.revisions WHERE version=%s',
                    (version,),
                )
            ).fetchone()
        if row is None:
            return False
        if hashlib.sha256(_json(row['manifest']).encode()).hexdigest() != row['manifest_sha256']:
            return False
        canonical = {_json(relation) for relation in row['manifest']['relations']}
        return all(_json(asdict(relation)) in canonical for relation in relations)
