"""Fixture-only component comparisons; relevance labels never influence retrieval."""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter

from app.application.knowledge import HybridKnowledgeRetrieval
from app.application.knowledge_ports import Embeddings, PublicGraph, PublicKnowledgeStore
from app.domain.catalog import ActiveCatalog, mentioned_products
from app.domain.errors import FailureCode, RejectedError
from app.domain.knowledge import (
    EmbeddingPurpose,
    KnowledgeChunk,
    KnowledgeHit,
    KnowledgeRevision,
    RetrievalStrategy,
    validate_vector,
)
from app.domain.language import Language


@dataclass(frozen=True, slots=True)
class StrategyObservation:
    strategy: str
    chunks: tuple[KnowledgeChunk, ...]
    hits: tuple[KnowledgeHit, ...]
    duration_ms: float
    relevant_hit: bool | None
    source_recall: float | None


@dataclass(frozen=True, slots=True)
class QueryObservation:
    question: str
    actual_product_scope: tuple[str, ...]
    observations: tuple[StrategyObservation, ...]


class FixtureKnowledgeEvaluator:
    def __init__(
        self,
        store: PublicKnowledgeStore,
        graph: PublicGraph,
        embeddings: Embeddings,
        retrieval: HybridKnowledgeRetrieval,
        active: ActiveCatalog,
        revision: KnowledgeRevision,
    ) -> None:
        if embeddings.spec.provider != 'fixture' or embeddings.spec != revision.embedding:
            raise ValueError('strategy comparisons support explicit synthetic fixtures only')
        self._store = store
        self._graph = graph
        self._embeddings = embeddings
        self._retrieval = retrieval
        self._active = active
        self._revision = revision

    async def evaluate(
        self,
        question: str,
        expected_ids: tuple[str, ...],
        language: Language = Language.ES,
    ) -> QueryObservation:
        if not await self._retrieval.ready(self._active):
            raise RejectedError(FailureCode.DEPENDENCY_UNAVAILABLE)
        # Identical to the first-turn GraphComposer scope: no reference labels or manual
        # expected product annotations enter search, graph seeds or comparison anchors.
        products = tuple(sorted(mentioned_products(question, self._active.catalog)))
        allowed = frozenset(products)
        started = perf_counter()
        lexical = await self._store.lexical_candidates(self._revision.version, question, 12)
        if any(hit.strategy is not RetrievalStrategy.LEXICAL for hit in lexical):
            raise RejectedError(FailureCode.CATALOG_UNAVAILABLE)
        canonical_lexical = await self._retrieval.verify_hits(self._revision, lexical, allowed)
        lexical_chunks = self._ordered(lexical, canonical_lexical)
        observations = [self._observation('lexical', lexical_chunks, lexical, started, expected_ids)]

        started = perf_counter()
        vectors = await self._embeddings.encode((question,), EmbeddingPurpose.QUERY)
        if len(vectors) != 1:
            raise RejectedError(FailureCode.DEPENDENCY_UNAVAILABLE)
        validate_vector(vectors[0], self._revision.embedding)
        vector = await self._store.vector_candidates(self._revision.version, vectors[0], 12)
        if any(hit.strategy is not RetrievalStrategy.VECTOR for hit in vector):
            raise RejectedError(FailureCode.CATALOG_UNAVAILABLE)
        canonical_vector = await self._retrieval.verify_hits(self._revision, vector, allowed)
        observations.append(
            self._observation(
                'vector_hash64_fixture',
                self._ordered(vector, canonical_vector),
                vector,
                started,
                expected_ids,
            )
        )

        started = perf_counter()
        seeds = tuple(canonical_lexical)[:12]
        graph = await self._graph.candidates(self._revision.version, seeds, 12) if seeds else ()
        if any(hit.strategy is not RetrievalStrategy.GRAPH for hit in graph):
            raise RejectedError(FailureCode.CATALOG_UNAVAILABLE)
        canonical_graph = await self._retrieval.verify_hits(
            self._revision,
            graph,
            allowed,
            frozenset(seeds),
        )
        observations.append(
            self._observation(
                'graph_lexical_seeded',
                self._ordered(graph, canonical_graph),
                graph,
                started,
                expected_ids,
            )
        )

        started = perf_counter()
        hybrid = await self._retrieval.retrieve(self._active, question, products, language)
        if hybrid.revision != self._revision:
            raise RejectedError(FailureCode.CATALOG_UNAVAILABLE)
        observations.append(
            self._observation(
                'hybrid',
                hybrid.chunks,
                (),
                started,
                expected_ids,
            )
        )
        if await self._store.active_revision() != self._revision:
            raise RejectedError(FailureCode.CATALOG_UNAVAILABLE)
        return QueryObservation(question, products, tuple(observations))

    @staticmethod
    def _ordered(
        hits: tuple[KnowledgeHit, ...],
        canonical: dict[str, KnowledgeChunk],
    ) -> tuple[KnowledgeChunk, ...]:
        ids = dict.fromkeys(hit.chunk_id for hit in hits if hit.chunk_id in canonical)
        return tuple(canonical[cid] for cid in ids)

    @staticmethod
    def _observation(
        strategy: str,
        chunks: tuple[KnowledgeChunk, ...],
        hits: tuple[KnowledgeHit, ...],
        started: float,
        expected_ids: tuple[str, ...],
    ) -> StrategyObservation:
        expected = frozenset(expected_ids)
        found = expected.intersection(chunk.id for chunk in chunks)
        return StrategyObservation(
            strategy,
            chunks,
            hits,
            (perf_counter() - started) * 1000,
            bool(found) if expected else None,
            len(found) / len(expected) if expected else None,
        )
