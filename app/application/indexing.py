"""Explicit public indexing; one active pointer after both projections verify."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from app.application.knowledge_ports import Embeddings, PublicGraph, PublicKnowledgeStore
from app.domain.knowledge import EmbeddingPurpose, KnowledgeCorpus, ProjectionStamp, validate_vector


@dataclass(frozen=True, slots=True)
class IndexResult:
    version: str
    stamp: ProjectionStamp
    reused_vectors: bool


class KnowledgeIndexer:
    def __init__(
        self,
        store: PublicKnowledgeStore,
        graph: PublicGraph,
        embeddings: Embeddings,
        recover_index_reservations: Callable[[], Awaitable[int]],
    ) -> None:
        self._store = store
        self._graph = graph
        self._embeddings = embeddings
        self._recover = recover_index_reservations

    async def index(self, corpus: KnowledgeCorpus) -> IndexResult:
        if corpus.revision.embedding != self._embeddings.spec:
            raise ValueError('corpus and index embedding identities must match')
        expected = ProjectionStamp(
            corpus.revision.version,
            corpus.revision.catalog_sha256,
            len(corpus.chunks),
            len(corpus.entities),
            len(corpus.relations),
        )
        async with self._store.indexing_lock():
            # This lock proves there is no live owner of an old indexing reservation.
            # Recovery preserves its conservative cost and permits a late known settlement.
            await self._recover()
            existing = await self._store.projection_stamp(corpus.revision.version)
            if existing is not None and existing != expected:
                raise ValueError('staged knowledge does not match the requested corpus')
            vectors: tuple[tuple[float, ...], ...]
            if existing is not None:
                vectors = await self._store.vectors_for_indexing(
                    corpus.revision.version, tuple(chunk.id for chunk in corpus.chunks)
                )
            else:
                collected: list[tuple[float, ...]] = []
                batches: list[list[str]] = [[]]
                batch_bytes = 0
                for chunk in corpus.chunks:
                    size = len(chunk.text.encode('utf-8'))
                    if batches[-1] and (len(batches[-1]) == 32 or batch_bytes + size > 240_000):
                        batches.append([])
                        batch_bytes = 0
                    batches[-1].append(chunk.text)
                    batch_bytes += size
                for batch in batches:
                    encoded = await self._embeddings.encode(tuple(batch), EmbeddingPurpose.INDEX)
                    if len(encoded) != len(batch):
                        raise ValueError('index embedding cardinality mismatch')
                    collected.extend(encoded)
                vectors = tuple(collected)
            if len(vectors) != len(corpus.chunks):
                raise ValueError('staged embedding cardinality mismatch')
            for vector in vectors:
                validate_vector(vector, corpus.revision.embedding)
            # Even reuse passes immutable manifest/vector validation; a matching count alone
            # cannot accept a changed extractor, corrupted row or foreign staged projection.
            await self._store.stage(corpus, vectors)
            await self._graph.stage(corpus)
            actual = await self._graph.projection_stamp(corpus.revision.version)
            if actual != expected or await self._store.projection_stamp(corpus.revision.version) != expected:
                raise ValueError('public projections did not produce the expected proof')
            await self._store.mark_prepared(corpus.revision.version, actual)
            await self._store.activate_prepared(corpus.revision.version)
            return IndexResult(corpus.revision.version, actual, existing is not None)
