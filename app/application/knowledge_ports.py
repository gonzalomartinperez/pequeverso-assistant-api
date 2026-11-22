"""Public knowledge ports. Private conversations and accounting keep their existing stores."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from app.application.ports import CatalogRepository

if TYPE_CHECKING:
    from contextlib import AbstractAsyncContextManager

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
    """Track embedding token reservations and reported usage."""

    async def reserve(self, max_input_tokens: int, purpose: EmbeddingPurpose) -> str:
        """Reserve up to the stated input token count and return the operation ID."""
        ...

    async def settle(self, operation_id: str, input_tokens: int) -> None:
        """Settle the operation using the reported input token count."""
        ...

    async def mark_unreported(self, operation_id: str) -> None:
        """Mark the operation as closed without reported usage."""
        ...


class Embeddings(Protocol):
    """Expose the embedding specification and encode text with that specification."""

    @property
    def spec(self) -> EmbeddingSpec:
        """Return the embedding specification used by the encoder."""
        ...

    async def encode(
        self, texts: tuple[str, ...], purpose: EmbeddingPurpose
    ) -> tuple[tuple[float, ...], ...]:
        """Encode the texts into vectors in input order for the given purpose."""
        ...


class PublicKnowledgeStore(CatalogRepository, Protocol):
    """PG owns the only public active pointer.

    Runtime binding requires a prepared version matching the catalog hash, configured
    parser and embedding specification; it must never select an arbitrary latest row.
    """

    def indexing_lock(self) -> AbstractAsyncContextManager[None]:
        """Provide a context manager that serializes indexing work."""
        ...

    async def stage(self, corpus: KnowledgeCorpus, vectors: tuple[tuple[float, ...], ...]) -> None:
        """Stage a public knowledge corpus and its vectors for indexing."""
        ...

    async def vectors_for_indexing(
        self, version: str, ids: tuple[str, ...]
    ) -> tuple[tuple[float, ...], ...]:
        """Reuse a bounded staged embedding set in explicit indexing, preserving input order."""
        ...

    async def projection_stamp(self, version: str) -> ProjectionStamp | None:
        """Return the canonical projection stamp for the version, if present."""
        ...

    async def mark_prepared(self, version: str, graph_stamp: ProjectionStamp) -> None:
        """Compare the observed graph proof against staged canonical counts and hashes."""
        ...

    async def activate_prepared(self, version: str) -> None:
        """Make the prepared knowledge version active."""
        ...

    async def active_revision(self) -> KnowledgeRevision | None:
        """Return the active public knowledge revision, if present."""
        ...

    async def lexical_candidates(
        self, version: str, question: str, limit: int
    ) -> tuple[KnowledgeHit, ...]:
        """Find up to the requested limit of lexical matches in the given version."""
        ...

    async def vector_candidates(
        self, version: str, vector: tuple[float, ...], limit: int
    ) -> tuple[KnowledgeHit, ...]:
        """Find up to the requested limit of vector matches in the given version."""
        ...

    async def read_chunks(self, version: str, ids: tuple[str, ...]) -> tuple[KnowledgeChunk, ...]:
        """Read the requested chunks from the given version."""
        ...

    async def verify_relations(
        self, version: str, relations: tuple[KnowledgeRelation, ...]
    ) -> bool:
        """Validate graph-returned paths against canonical relations and provenance."""
        ...


class PublicGraph(Protocol):
    """Stage and query the graph projection of the public corpus."""

    async def stage(self, corpus: KnowledgeCorpus) -> None:
        """Stage the graph projection for the supplied corpus."""
        ...

    async def projection_stamp(self, version: str) -> ProjectionStamp | None:
        """Return the graph projection stamp for the version, if present."""
        ...

    async def candidates(
        self, version: str, supporting_chunk_ids: tuple[str, ...], limit: int
    ) -> tuple[KnowledgeHit, ...]:
        """Find graph candidates in the version using the supplied supporting chunk IDs."""
        ...


class KnowledgeRetrieval(Protocol):
    """Retrieve public knowledge for the active catalog."""

    async def retrieve(
        self, active: ActiveCatalog, question: str, product_ids: tuple[str, ...], language: Language
    ) -> RetrievedKnowledge:
        """Retrieve knowledge for the question, product IDs, and language."""
        ...

    async def ready(self, active: ActiveCatalog) -> bool:
        """Check whether retrieval is ready for the active catalog."""
        ...
