"""Typed retrieve → grounded answer graph, with no retries or external tracing."""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from dataclasses import dataclass, replace
from typing import TypedDict

from langchain_core.documents import Document
from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from langsmith import tracing_context

from app.ai.composer import GroundedComposer
from app.application.knowledge_ports import KnowledgeRetrieval
from app.application.ports import (
    ComposerEvent,
    DeltaEvent,
    DispatchAwarePreparedTurn,
    DraftEvent,
    GenerationError,
    PreparedTurn,
    Turn,
)
from app.domain.budget import Usage
from app.domain.catalog import mentioned_products
from app.domain.conversation import Role
from app.domain.errors import FailureCode, RejectedError
from app.domain.knowledge import ChunkKind, RetrievedKnowledge
from app.domain.web_evidence import WebEvidence


@dataclass(slots=True, repr=False)
class GraphPrepared:
    turn: Turn
    baseline: PreparedTurn
    reservation_bytes: int
    resolved: PreparedTurn | None = None
    retrieval: RetrievedKnowledge | None = None
    sent_chunk_ids: tuple[str, ...] = ()

    @property
    def input_size_bytes(self) -> int:
        return self.reservation_bytes

    @property
    def web_evidence(self) -> tuple[WebEvidence, ...]:
        return (self.resolved or self.baseline).web_evidence

    @property
    def catalog_source_ids(self) -> frozenset[str]:
        return self.resolved.catalog_source_ids if self.resolved else frozenset()

    @property
    def generation_started(self) -> bool:
        return isinstance(self.resolved, DispatchAwarePreparedTurn) and self.resolved.generation_started


class _State(TypedDict):
    prepared: GraphPrepared


class GraphAnswerComposer:
    def __init__(
        self, grounded: GroundedComposer, retrieval: KnowledgeRetrieval, max_input_bytes: int
    ) -> None:
        self._grounded = grounded
        self._retrieval = retrieval
        self._max_input_bytes = max_input_bytes
        builder = StateGraph(_State)
        builder.add_node('retrieve', self._retrieve, retry_policy=())
        builder.add_node('answer', self._answer, retry_policy=())
        builder.add_edge(START, 'retrieve')
        builder.add_edge('retrieve', 'answer')
        builder.add_edge('answer', END)
        # Private history/idempotency remains in SQLite. No replay of a paid node.
        self._graph = builder.compile(checkpointer=False, store=None, cache=None, debug=False)

    @property
    def model(self) -> str:
        return self._grounded.model

    def prepare(self, turn: Turn) -> PreparedTurn:
        # No query embedding, DB lookup or provider I/O before the generation reservation.
        baseline = self._grounded.prepare(turn)
        limit = min(self._max_input_bytes, turn.input_size_limit or self._max_input_bytes)
        return GraphPrepared(turn, baseline, max(limit, baseline.input_size_bytes))

    async def _retrieve(self, state: _State) -> dict[str, GraphPrepared]:
        prepared = state['prepared']
        turn = prepared.turn
        products = tuple(sorted(mentioned_products(turn.question, turn.active.catalog)))
        if not products:
            products = next(
                (
                    tuple(product.id for product in message.details.products)
                    for message in reversed(turn.history)
                    if message.role is Role.ASSISTANT and message.details.products
                ),
                (),
            )
        knowledge = await self._retrieval.retrieve(turn.active, turn.question, products, turn.language)
        if knowledge.revision.catalog_sha256 != turn.active.sha256 or not knowledge.chunks:
            raise RejectedError(FailureCode.CATALOG_UNAVAILABLE)
        # LangChain is a document adapter only. Canonical content and source identities remain
        # explicit: graph relationships never become instructions, transactions or new facts.
        documents = tuple(
            Document(
                page_content=chunk.text,
                metadata={
                    'source_id': chunk.source_id,
                    'sha256': chunk.sha256,
                    'kind': chunk.kind.value,
                },
                id=chunk.id,
            )
            for chunk in knowledge.chunks
        )
        selected: list[Document] = []
        resolved: PreparedTurn | None = None
        for candidate in documents:
            proposed = [*selected, candidate]
            document_ids = frozenset(
                source_id
                for document in proposed
                if document.metadata.get('kind') == ChunkKind.DOCUMENT.value
                and isinstance(source_id := document.metadata.get('source_id'), str)
            )
            payload = json.dumps(
                {
                    'version': knowledge.revision.version,
                    'catalog_sha256': knowledge.revision.catalog_sha256,
                    'passages': [
                        {'id': item.id, 'text': item.page_content, **item.metadata} for item in proposed
                    ],
                },
                ensure_ascii=False,
                separators=(',', ':'),
            )
            trial = self._grounded.prepare_selected(
                replace(turn, web_evidence=prepared.baseline.web_evidence), document_ids, payload
            )
            if trial.input_size_bytes <= prepared.reservation_bytes:
                selected = proposed
                resolved = trial
        if resolved is None:
            raise RejectedError(FailureCode.INVALID_REQUEST)
        prepared.retrieval = knowledge
        prepared.resolved = resolved
        prepared.sent_chunk_ids = tuple(document.id for document in selected if document.id is not None)
        return {'prepared': prepared}

    async def _answer(self, state: _State) -> dict[str, GraphPrepared]:
        prepared = state['prepared']
        if prepared.resolved is None:
            raise RejectedError(FailureCode.CATALOG_UNAVAILABLE)
        writer = get_stream_writer()
        stream = self._grounded.compose(prepared.resolved)
        try:
            async for event in stream:
                writer(event)
        finally:
            await stream.aclose()
        return {'prepared': prepared}

    async def compose(self, prepared: PreparedTurn) -> AsyncGenerator[ComposerEvent]:
        if not isinstance(prepared, GraphPrepared):
            raise TypeError('graph composer requires its own prepared turn')
        # Override ambient LANGSMITH/LANGCHAIN tracing variables for the whole async lifetime.
        # No client wrapping, evaluator uploads, callbacks or external tracing are configured.
        with tracing_context(enabled=False):
            stream = self._graph.astream(
                {'prepared': prepared},
                config={'recursion_limit': 4, 'callbacks': []},
                stream_mode='custom',
            )
            if not isinstance(stream, AsyncGenerator):
                raise TypeError('graph stream must support explicit cancellation')
            try:
                async for event in stream:
                    if not isinstance(event, (DeltaEvent, DraftEvent)):
                        raise RejectedError(FailureCode.GENERATION_FAILED)
                    yield event
            except GenerationError:
                raise
            except RejectedError as error:
                usage = None if prepared.generation_started else Usage(0, 0)
                raise GenerationError(error.code, usage) from error
            finally:
                await stream.aclose()
