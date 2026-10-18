"""Explicit indexing orchestration: fake ports, zero SDK/network/cost; SQL/Neo have separate tests."""

import asyncio
import hashlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from app.application.indexing import KnowledgeIndexer
from app.application.ports import StoredSnapshot
from app.domain.catalog import Catalog
from app.domain.knowledge import (
    ChunkKind,
    EmbeddingPurpose,
    EmbeddingSpec,
    EntityKind,
    KnowledgeChunk,
    KnowledgeCorpus,
    KnowledgeEntity,
    KnowledgeHit,
    KnowledgeRelation,
    KnowledgeRevision,
    ProjectionStamp,
)

SPEC = EmbeddingSpec('fixture', 'hash64-v1', 64)
VECTOR = (1.0,) + (0.0,) * 63


def corpus(count: int = 2, text: str = 'Published authorized content.') -> KnowledgeCorpus:
    body = b'{}'
    chunks = tuple(
        KnowledgeChunk(
            f'product:{i}',
            ChunkKind.PRODUCT,
            str(i),
            f'Product {i}',
            text,
            f'https://pequeverso.com/product-{i}/',
            (str(i),),
            hashlib.sha256(text.encode()).hexdigest(),
            f'/products/{i}',
        )
        for i in range(count)
    )
    return KnowledgeCorpus(
        KnowledgeRevision('a' * 64, hashlib.sha256(body).hexdigest(), 'b' * 40, 'test-v1', SPEC),
        body,
        datetime(2026, 10, 17, tzinfo=UTC),
        chunks,
        tuple(KnowledgeEntity(c.id, EntityKind.PRODUCT, c.title, (c.id,)) for c in chunks),
        (),
    )


def stamp(value: KnowledgeCorpus) -> ProjectionStamp:
    return ProjectionStamp(
        value.revision.version,
        value.revision.catalog_sha256,
        len(value.chunks),
        len(value.entities),
        len(value.relations),
    )


class Store:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.locked = False
        self.staged: KnowledgeCorpus | None = None
        self.vectors: tuple[tuple[float, ...], ...] = ()
        self.proof: ProjectionStamp | None = None
        self.active_version = 'previous-active'
        self.prepared = False
        self.reject_reused_content = False
        self.corrupt_after_stage = False

    @asynccontextmanager
    async def indexing_lock(self) -> AsyncIterator[None]:
        assert not self.locked
        self.locked = True
        self.events.append('lock')
        try:
            yield
        finally:
            self.events.append('unlock')
            self.locked = False

    async def projection_stamp(self, version: str) -> ProjectionStamp | None:
        assert self.locked
        self.events.append('pg-proof')
        return self.proof

    async def vectors_for_indexing(self, version: str, ids: tuple[str, ...]) -> tuple[tuple[float, ...], ...]:
        assert self.locked and self.staged is not None
        assert ids == tuple(chunk.id for chunk in self.staged.chunks)
        self.events.append('reuse')
        return self.vectors

    async def stage(self, value: KnowledgeCorpus, vectors: tuple[tuple[float, ...], ...]) -> None:
        assert self.locked
        self.events.append('pg-stage')
        if self.reject_reused_content:
            raise ValueError('immutable canonical projection mismatch')
        self.staged, self.vectors = value, vectors
        self.proof = stamp(value)
        if self.corrupt_after_stage:
            self.proof = replace(self.proof, chunk_count=0)

    async def mark_prepared(self, version: str, graph_stamp: ProjectionStamp) -> None:
        assert self.locked and self.proof == graph_stamp
        self.events.append('prepared')
        self.prepared = True

    async def activate_prepared(self, version: str) -> None:
        assert self.locked and self.prepared
        self.events.append('activate')
        self.active_version = version

    # Unused runtime capabilities fail loudly: indexing must not read private/runtime state.
    async def active(self) -> StoredSnapshot | None:
        raise AssertionError('runtime catalog read during indexing')

    async def activate(
        self, sha256: str, body: bytes, catalog: Catalog, verified_at: datetime, attempted_at: datetime
    ) -> None:
        raise AssertionError('unprepared activation')

    async def mark_verified(self, sha256: str, verified_at: datetime, attempted_at: datetime) -> None:
        raise AssertionError('runtime refresh during indexing')

    async def record_failure(self, reason: str, now: datetime) -> None:
        raise AssertionError('runtime refresh during indexing')

    async def active_revision(self) -> KnowledgeRevision | None:
        raise AssertionError('runtime revision lookup during indexing')

    async def lexical_candidates(self, version: str, question: str, limit: int) -> tuple[KnowledgeHit, ...]:
        raise AssertionError('visitor search during indexing')

    async def vector_candidates(
        self, version: str, vector: tuple[float, ...], limit: int
    ) -> tuple[KnowledgeHit, ...]:
        raise AssertionError('visitor search during indexing')

    async def read_chunks(self, version: str, ids: tuple[str, ...]) -> tuple[KnowledgeChunk, ...]:
        raise AssertionError('visitor hydration during indexing')

    async def verify_relations(self, version: str, relations: tuple[KnowledgeRelation, ...]) -> bool:
        raise AssertionError('visitor graph validation during indexing')


class Graph:
    def __init__(self, store: Store, events: list[str]) -> None:
        self.store, self.events = store, events
        self.proof: ProjectionStamp | None = None
        self.fail = False
        self.corrupt = False

    async def stage(self, value: KnowledgeCorpus) -> None:
        assert self.store.locked
        self.events.append('graph-stage')
        if self.fail:
            raise RuntimeError('graph projection unavailable')
        self.proof = stamp(value)
        if self.corrupt:
            self.proof = replace(self.proof, entity_count=0)

    async def projection_stamp(self, version: str) -> ProjectionStamp | None:
        assert self.store.locked
        self.events.append('graph-proof')
        return self.proof

    async def candidates(
        self, version: str, supporting_chunk_ids: tuple[str, ...], limit: int
    ) -> tuple[KnowledgeHit, ...]:
        raise AssertionError('visitor graph search during indexing')


class Encoder:
    def __init__(self, store: Store, events: list[str]) -> None:
        self.store, self.events = store, events
        self.spec = SPEC
        self.calls: list[tuple[str, ...]] = []
        self.output: tuple[tuple[float, ...], ...] | None = None
        self.block = False
        self.entered = asyncio.Event()

    async def encode(
        self, texts: tuple[str, ...], purpose: EmbeddingPurpose
    ) -> tuple[tuple[float, ...], ...]:
        assert self.store.locked and purpose is EmbeddingPurpose.INDEX
        assert len(texts) <= 32 and sum(len(text.encode('utf-8')) for text in texts) <= 240_000
        self.events.append('encode')
        self.calls.append(texts)
        self.entered.set()
        if self.block:
            await asyncio.Event().wait()
        return self.output if self.output is not None else (VECTOR,) * len(texts)


class Rig:
    def __init__(self) -> None:
        self.events: list[str] = []
        self.store = Store(self.events)
        self.graph = Graph(self.store, self.events)
        self.encoder = Encoder(self.store, self.events)
        self.indexer = KnowledgeIndexer(self.store, self.graph, self.encoder, self.recover)

    async def recover(self) -> int:
        assert self.store.locked
        self.events.append('recover')
        return 1


def test_indexing_recovers_inside_lock_and_activates_only_after_both_proofs() -> None:
    async def run() -> None:
        rig, value = Rig(), corpus()
        result = await rig.indexer.index(value)
        assert not result.reused_vectors and result.stamp == stamp(value)
        assert rig.events == [
            'lock',
            'recover',
            'pg-proof',
            'encode',
            'pg-stage',
            'graph-stage',
            'graph-proof',
            'pg-proof',
            'prepared',
            'activate',
            'unlock',
        ]
        assert rig.store.active_version == value.revision.version
        assert not rig.store.locked

    asyncio.run(run())


def test_idempotent_index_reuses_vectors_without_a_second_embedding_request() -> None:
    async def run() -> None:
        rig, value = Rig(), corpus()
        await rig.indexer.index(value)
        rig.encoder.calls.clear()
        rig.events.clear()
        result = await rig.indexer.index(value)
        assert result.reused_vectors and rig.encoder.calls == []
        assert 'reuse' in rig.events and 'pg-stage' in rig.events and 'prepared' in rig.events

    asyncio.run(run())


def test_wrong_existing_proof_fails_before_embedding_or_activation() -> None:
    async def run() -> None:
        rig, value = Rig(), corpus()
        rig.store.proof = replace(stamp(value), catalog_sha256='f' * 64)
        with pytest.raises(ValueError, match='requested corpus'):
            await rig.indexer.index(value)
        assert rig.encoder.calls == []
        assert rig.store.active_version == 'previous-active'
        assert rig.events == ['lock', 'recover', 'pg-proof', 'unlock']

    asyncio.run(run())


@pytest.mark.parametrize('component', ['postgres', 'graph'])
def test_changed_post_stage_proof_never_prepares_or_activates(component: str) -> None:
    async def run() -> None:
        rig, value = Rig(), corpus()
        rig.store.corrupt_after_stage = component == 'postgres'
        rig.graph.corrupt = component == 'graph'
        with pytest.raises(ValueError, match='expected proof'):
            await rig.indexer.index(value)
        assert not rig.store.prepared and rig.store.active_version == 'previous-active'
        assert 'activate' not in rig.events and not rig.store.locked

    asyncio.run(run())


def test_graph_stage_failure_preserves_old_active_and_explicit_retry_reuses_vectors() -> None:
    async def run() -> None:
        rig, value = Rig(), corpus()
        rig.graph.fail = True
        with pytest.raises(RuntimeError, match='graph projection unavailable'):
            await rig.indexer.index(value)
        assert rig.store.active_version == 'previous-active' and not rig.store.prepared
        assert len(rig.encoder.calls) == 1 and rig.events.count('graph-stage') == 1
        rig.graph.fail = False
        result = await rig.indexer.index(value)
        assert result.reused_vectors and len(rig.encoder.calls) == 1
        assert rig.store.active_version == value.revision.version

    asyncio.run(run())


def test_reused_manifest_is_revalidated_before_graph_or_activation() -> None:
    async def run() -> None:
        rig, value = Rig(), corpus()
        rig.store.staged, rig.store.proof = value, stamp(value)
        rig.store.vectors = (VECTOR,) * len(value.chunks)
        rig.store.reject_reused_content = True
        with pytest.raises(ValueError, match='immutable canonical'):
            await rig.indexer.index(value)
        assert rig.encoder.calls == [] and 'pg-stage' in rig.events
        assert 'graph-stage' not in rig.events and rig.store.active_version == 'previous-active'

    asyncio.run(run())


@pytest.mark.parametrize('reuse', [False, True])
@pytest.mark.parametrize('invalid', ['missing', 'dimensions', 'zero', 'nonfinite'])
def test_missing_or_invalid_vectors_never_reach_activation(reuse: bool, invalid: str) -> None:
    async def run() -> None:
        rig, value = Rig(), corpus()
        bad = {
            'missing': (),
            'dimensions': ((1.0,),) * 2,
            'zero': ((0.0,) * 64,) * 2,
            'nonfinite': ((float('nan'),) * 64,) * 2,
        }[invalid]
        if reuse:
            rig.store.staged, rig.store.proof, rig.store.vectors = value, stamp(value), bad
        else:
            rig.encoder.output = bad
        with pytest.raises(ValueError, match=r'cardinality|embedding|norm'):
            await rig.indexer.index(value)
        assert 'pg-stage' not in rig.events and 'graph-stage' not in rig.events
        assert rig.store.active_version == 'previous-active' and not rig.store.locked
        assert len(rig.encoder.calls) == (0 if reuse else 1)

    asyncio.run(run())


def test_embedding_identity_mismatch_has_no_lock_recovery_or_provider_effect() -> None:
    async def run() -> None:
        rig = Rig()
        rig.encoder.spec = EmbeddingSpec('openai', 'text-embedding-3-small', 1536)
        with pytest.raises(ValueError, match='identities must match'):
            await rig.indexer.index(corpus())
        assert rig.events == [] and rig.encoder.calls == []

    asyncio.run(run())


def test_greedy_batches_count_utf8_bytes_and_split_32_maximum_chunks_into_30_and_2() -> None:
    async def run() -> None:
        rig = Rig()
        result = await rig.indexer.index(corpus(32, 'é' * 4000))
        assert [len(batch) for batch in rig.encoder.calls] == [30, 2]
        assert [sum(len(text.encode('utf-8')) for text in batch) for batch in rig.encoder.calls] == [
            240_000,
            16_000,
        ]
        assert not result.reused_vectors

    asyncio.run(run())


def test_greedy_batches_also_enforce_32_items_for_small_chunks() -> None:
    async def run() -> None:
        rig = Rig()
        await rig.indexer.index(corpus(65))
        assert [len(batch) for batch in rig.encoder.calls] == [32, 32, 1]

    asyncio.run(run())


def test_cancellation_releases_index_lock_without_automatic_retry_or_activation() -> None:
    async def run() -> None:
        rig = Rig()
        rig.encoder.block = True
        task = asyncio.create_task(rig.indexer.index(corpus()))
        await rig.encoder.entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert len(rig.encoder.calls) == 1 and rig.events.count('recover') == 1
        assert rig.events[-1] == 'unlock' and not rig.store.locked
        assert 'pg-stage' not in rig.events and rig.store.active_version == 'previous-active'

    asyncio.run(run())
