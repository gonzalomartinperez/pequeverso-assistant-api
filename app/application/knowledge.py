"""Bounded hybrid retrieval. PostgreSQL validates every fact and graph path before use."""

from __future__ import annotations

from app.application.knowledge_ports import Embeddings, PublicGraph, PublicKnowledgeStore
from app.application.ports import Clock
from app.domain.catalog import ActiveCatalog, PriceStatus
from app.domain.errors import FailureCode, RejectedError
from app.domain.knowledge import (
    ChunkKind,
    EmbeddingPurpose,
    KnowledgeChunk,
    KnowledgeHit,
    KnowledgeRevision,
    ProjectionStamp,
    RelationKind,
    RetrievalStrategy,
    RetrievedKnowledge,
    validate_vector,
)
from app.domain.language import Language

_CANDIDATES = 12
_RESULTS = 8


class HybridKnowledgeRetrieval:
    def __init__(
        self,
        store: PublicKnowledgeStore,
        graph: PublicGraph,
        embeddings: Embeddings,
        parser_version: str,
        clock: Clock,
    ) -> None:
        self._store = store
        self._graph = graph
        self._embeddings = embeddings
        self._parser_version = parser_version
        self._clock = clock

    async def _revision(self, active: ActiveCatalog) -> KnowledgeRevision:
        if active.price_status(self._clock.now()) is not PriceStatus.VERIFIED:
            raise RejectedError(FailureCode.CATALOG_UNAVAILABLE)
        revision = await self._store.active_revision()
        if (
            revision is None
            or revision.catalog_sha256 != active.sha256
            or revision.source_revision != active.catalog.source_revision
            or revision.parser_version != self._parser_version
            or revision.embedding != self._embeddings.spec
        ):
            raise RejectedError(FailureCode.CATALOG_UNAVAILABLE)
        return revision

    async def _graph_current(self, revision: KnowledgeRevision) -> bool:
        pg = await self._store.projection_stamp(revision.version)
        try:
            graph = await self._graph.projection_stamp(revision.version)
        except RejectedError as error:
            if error.code is not FailureCode.DEPENDENCY_UNAVAILABLE:
                raise
            return False
        return self._matching_stamp(revision, pg, graph)

    @staticmethod
    def _matching_stamp(
        revision: KnowledgeRevision,
        pg: ProjectionStamp | None,
        graph: ProjectionStamp | None,
    ) -> bool:
        return (
            pg is not None
            and pg == graph
            and pg.version == revision.version
            and pg.catalog_sha256 == revision.catalog_sha256
        )

    async def ready(self, active: ActiveCatalog) -> bool:
        try:
            revision = await self._revision(active)
            return await self._graph_current(revision)
        except (RejectedError, OSError, TimeoutError, ValueError, TypeError):
            return False

    async def retrieve(
        self,
        active: ActiveCatalog,
        question: str,
        product_ids: tuple[str, ...],
        language: Language,
    ) -> RetrievedKnowledge:
        # The caller supplies a redacted visitor question. It is embedded once, not persisted
        # as knowledge, and never transformed into executable SQL or Cypher.
        if not question.strip() or len(question.encode('utf-8')) > 8000:
            raise RejectedError(FailureCode.INVALID_REQUEST)
        allowed = frozenset(product_ids)
        if not allowed.issubset({p.id for p in active.catalog.products}):
            raise RejectedError(FailureCode.INVALID_REQUEST)
        revision = await self._revision(active)
        lexical = await self._store.lexical_candidates(revision.version, question, _CANDIDATES)
        vectors = await self._embeddings.encode((question,), EmbeddingPurpose.QUERY)
        if len(vectors) != 1:
            raise RejectedError(FailureCode.DEPENDENCY_UNAVAILABLE)
        validate_vector(vectors[0], revision.embedding)
        semantic = await self._store.vector_candidates(revision.version, vectors[0], _CANDIDATES)
        if any(hit.strategy is not RetrievalStrategy.LEXICAL for hit in lexical) or any(
            hit.strategy is not RetrievalStrategy.VECTOR for hit in semantic
        ):
            raise RejectedError(FailureCode.CATALOG_UNAVAILABLE)
        initial = await self._verified(revision, lexical + semantic, allowed)
        graph_current = await self._graph_current(revision)
        graph_hits: tuple[KnowledgeHit, ...] = ()
        if graph_current and initial:
            try:
                graph_hits = await self._graph.candidates(
                    revision.version,
                    tuple(initial)[:_CANDIDATES],
                    _CANDIDATES,
                )
            except RejectedError as error:
                if error.code is not FailureCode.DEPENDENCY_UNAVAILABLE:
                    raise
                graph_current = False
        if any(hit.strategy is not RetrievalStrategy.GRAPH for hit in graph_hits):
            raise RejectedError(FailureCode.CATALOG_UNAVAILABLE)
        verified = await self._verified(
            revision, lexical + semantic + graph_hits, allowed, frozenset(tuple(initial)[:_CANDIDATES])
        )
        scores: dict[str, float] = {}
        strategies: list[RetrievalStrategy] = []
        # Reciprocal rank avoids comparing unrelated SQL/vector/graph score scales.
        for strategy, weight, hits in (
            (RetrievalStrategy.LEXICAL, 1.0, lexical),
            (RetrievalStrategy.VECTOR, 0.8, semantic),
            (RetrievalStrategy.GRAPH, 0.6, graph_hits),
        ):
            seen: set[str] = set()
            for rank, hit in enumerate(hits[:_CANDIDATES]):
                if hit.chunk_id in verified and hit.chunk_id not in seen:
                    seen.add(hit.chunk_id)
                    scores[hit.chunk_id] = scores.get(hit.chunk_id, 0.0) + weight / (rank + 1)
                    if strategy not in strategies:
                        strategies.append(strategy)
        ordered = sorted(scores, key=lambda cid: (-scores[cid], cid))
        # Comparison anchors must include each named product even when one search ranks
        # below the other. These are still exact PG chunks, never invented index content.
        anchors = await self._store.read_chunks(
            revision.version,
            tuple(f'product:{pid}' for pid in product_ids),
        )
        expected_anchors = {f'product:{pid}' for pid in product_ids}
        if len(anchors) != len(expected_anchors) or {c.id for c in anchors} != expected_anchors:
            raise RejectedError(FailureCode.CATALOG_UNAVAILABLE)
        for anchor in anchors:
            if (
                anchor.kind is not ChunkKind.PRODUCT
                or anchor.id != f'product:{anchor.source_id}'
                or anchor.source_id not in allowed
                or anchor.product_ids != (anchor.source_id,)
            ):
                raise RejectedError(FailureCode.CATALOG_UNAVAILABLE)
            verified[anchor.id] = anchor
        selected = tuple(dict.fromkeys([c.id for c in anchors] + ordered))[:_RESULTS]
        if await self._store.active_revision() != revision:
            # No mixed-version answer across an activation race. The visitor may retry;
            # this invocation never retries retrieval or generation automatically.
            raise RejectedError(FailureCode.CATALOG_UNAVAILABLE)
        return RetrievedKnowledge(
            revision, tuple(verified[cid] for cid in selected), tuple(strategies), not graph_current
        )

    async def _verified(
        self,
        revision: KnowledgeRevision,
        hits: tuple[KnowledgeHit, ...],
        allowed: frozenset[str],
        graph_seeds: frozenset[str] = frozenset(),
    ) -> dict[str, KnowledgeChunk]:
        if len(hits) > _CANDIDATES * 3:
            raise RejectedError(FailureCode.DEPENDENCY_UNAVAILABLE)
        if any(h.version != revision.version for h in hits):
            raise RejectedError(FailureCode.CATALOG_UNAVAILABLE)
        for hit in hits:
            if hit.strategy is RetrievalStrategy.GRAPH and (
                not self._connected_path(hit, graph_seeds)
                or not await self._store.verify_relations(revision.version, hit.relations)
            ):
                raise RejectedError(FailureCode.CATALOG_UNAVAILABLE)
        canonical = await self._store.read_chunks(
            revision.version,
            tuple(dict.fromkeys(hit.chunk_id for hit in hits)),
        )
        chunks = {chunk.id: chunk for chunk in canonical}
        if len(chunks) != len(canonical) or set(chunks) != {hit.chunk_id for hit in hits}:
            raise RejectedError(FailureCode.CATALOG_UNAVAILABLE)
        for hit in hits:
            chunk = chunks.get(hit.chunk_id)
            if chunk is None or chunk.sha256 != hit.sha256:
                raise RejectedError(FailureCode.CATALOG_UNAVAILABLE)
        return {
            cid: chunk
            for cid, chunk in chunks.items()
            if not allowed or allowed.intersection(chunk.product_ids)
        }

    @staticmethod
    def _connected_path(hit: KnowledgeHit, seeds: frozenset[str]) -> bool:
        relations = hit.relations
        if not 1 <= len(relations) <= 2 or len(set(relations)) != len(relations):
            return False
        degrees: dict[str, int] = {}
        for relation in relations:
            for endpoint in (relation.subject_id, relation.object_id):
                degrees[endpoint] = degrees.get(endpoint, 0) + 1
        endpoints = [node for node, degree in degrees.items() if degree == 1]
        if len(endpoints) != 2 or len(degrees) != len(relations) + 1:
            return False

        def supported(entity_id: str, chunks: frozenset[str]) -> bool:
            return entity_id in chunks or any(
                relation.predicate is RelationKind.HAS_TOPIC
                and relation.object_id == entity_id
                and relation.supporting_chunk_id in chunks
                for relation in relations
            )

        left, right = endpoints
        target = frozenset({hit.chunk_id})
        return (supported(left, seeds) and supported(right, target)) or (
            supported(right, seeds) and supported(left, target)
        )
