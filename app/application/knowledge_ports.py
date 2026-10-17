"""Public knowledge ports. Private conversations and accounting keep their existing stores."""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from typing import Protocol

from app.application.ports import CatalogRepository
from app.domain.catalog import ActiveCatalog
from app.domain.knowledge import (
    EmbeddingPurpose,
    EmbeddingSpec,
    KnowledgeChunk,
    KnowledgeCorpus,
    KnowledgeHit,
    KnowledgeRelation,
    KnowledgeRevision,
    ProjectionStamp,
    RetrievedKnowledge,
)
from app.domain.language import Language


class EmbeddingAccounting(Protocol):
    async def reserve(self, max_input_tokens: int, purpose: EmbeddingPurpose) -> str: ...
    async def settle(self, operation_id: str, input_tokens: int) -> None: ...
    async def mark_unreported(self, operation_id: str) -> None: ...


class Embeddings(Protocol):
    @property
    def spec(self) -> EmbeddingSpec: ...

    async def encode(
        self, texts: tuple[str, ...], purpose: EmbeddingPurpose
    ) -> tuple[tuple[float, ...], ...]: ...


class PublicKnowledgeStore(CatalogRepository, Protocol):
    """PG owns the only public active pointer.

    Runtime binding requires a prepared version matching the catalog hash, configured
    parser and embedding specification; it must never select an arbitrary latest row.
    """

    def indexing_lock(self) -> AbstractAsyncContextManager[None]: ...
    async def stage(self, corpus: KnowledgeCorpus, vectors: tuple[tuple[float, ...], ...]) -> None: ...
    async def projection_stamp(self, version: str) -> ProjectionStamp | None: ...
    async def mark_prepared(self, version: str, graph_stamp: ProjectionStamp) -> None:
        """Compare the observed graph proof against staged canonical counts and hashes."""
        ...
    async def activate_prepared(self, version: str) -> None: ...
    async def active_revision(self) -> KnowledgeRevision | None: ...
    async def lexical_candidates(
        self, version: str, question: str, limit: int
    ) -> tuple[KnowledgeHit, ...]: ...
    async def vector_candidates(
        self, version: str, vector: tuple[float, ...], limit: int
    ) -> tuple[KnowledgeHit, ...]: ...
    async def read_chunks(self, version: str, ids: tuple[str, ...]) -> tuple[KnowledgeChunk, ...]: ...
    async def verify_relations(self, version: str, relations: tuple[KnowledgeRelation, ...]) -> bool:
        """Validate graph-returned paths against canonical relations and provenance."""
        ...


class PublicGraph(Protocol):
    async def stage(self, corpus: KnowledgeCorpus) -> None: ...
    async def projection_stamp(self, version: str) -> ProjectionStamp | None: ...
    async def candidates(
        self, version: str, supporting_chunk_ids: tuple[str, ...], limit: int
    ) -> tuple[KnowledgeHit, ...]: ...


class KnowledgeRetrieval(Protocol):
    async def retrieve(
        self, active: ActiveCatalog, question: str, product_ids: tuple[str, ...], language: Language
    ) -> RetrievedKnowledge: ...

    async def ready(self, active: ActiveCatalog) -> bool: ...
