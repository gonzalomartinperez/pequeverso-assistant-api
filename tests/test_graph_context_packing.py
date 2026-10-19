"""Regression for a genuine second-turn failure found in the exact GraphRAG image."""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import replace
from datetime import timedelta

import pytest

from app.adapters.catalog.knowledge import build_public_corpus
from app.adapters.catalog_schema import CatalogParser
from app.adapters.graph.composer import GraphAnswerComposer, GraphPrepared
from app.adapters.providers.openai_embeddings import FixtureHashEmbeddings
from app.ai.composer import ComposerSettings, GroundedComposer
from app.ai.evidence import decode_documents
from app.application.ports import DraftEvent, GenerationError, Turn
from app.domain.catalog import ActiveCatalog, DocumentKind, PriceStatus
from app.domain.conversation import AnswerDetails, Message, ProductRef, Role
from app.domain.errors import FailureCode
from app.domain.knowledge import RetrievalStrategy, RetrievedKnowledge
from app.domain.language import Language
from tests.support import CATALOG_BYTES, ScriptedProvider

PARSER = CatalogParser(frozenset({'pequeverso.com', 'consumer.hotmart.com', 'refund.hotmart.com'}))
CATALOG = PARSER(CATALOG_BYTES)
FIRST_ANSWER = (
    'Según la información de la tienda: Recibes el material principal, Grafismo Fonético '
    'Paso a Paso, y ocho bonos incluidos en el mismo pago: guía, tarjetas, reto, animales, '
    'juegos, sonidos del hogar, pósteres y actividades sobre el nombre y la familia. '
    'En total, 9 PDF y 414 páginas. Los bonos no se pagan aparte.'
)


class PublicRetrieval:
    def __init__(self, *, product_only: bool = False) -> None:
        self.product_only = product_only

    async def ready(self, active: ActiveCatalog) -> bool:
        return active.sha256 == hashlib.sha256(CATALOG_BYTES).hexdigest()

    async def retrieve(
        self, active: ActiveCatalog, question: str, product_ids: tuple[str, ...], language: Language
    ) -> RetrievedKnowledge:
        corpus = build_public_corpus(CATALOG_BYTES, active.verified_at, FixtureHashEmbeddings().spec, PARSER)
        chunks = tuple(c for c in corpus.chunks if not self.product_only or c.kind.value == 'product')
        return RetrievedKnowledge(corpus.revision, chunks, (RetrievalStrategy.LEXICAL,))


@pytest.mark.parametrize('product_only', [False, True], ids=['mixed-evidence', 'catalog-product-anchors'])
@pytest.mark.parametrize(
    'previous_answer',
    [FIRST_ANSWER, 'Información publicada del producto. ' * 35],
    ids=['exact-fixture-followup', 'long-answer-followup'],
)
def test_followup_comparison_keeps_facts_referents_and_whole_passages_within_24kb(
    previous_answer: str,
    product_only: bool,
) -> None:
    async def scenario() -> None:
        active = ActiveCatalog(
            CATALOG, hashlib.sha256(CATALOG_BYTES).hexdigest(), CATALOG.generated_at, timedelta(hours=168)
        )
        product = CATALOG.products[0]
        reference = ProductRef(
            product.id,
            product.name,
            product.summary,
            product.age_range,
            'https://pequeverso.com' + product.path,
            'https://pequeverso.com' + product.purchase_path,
            None,
            None,
        )
        history = (
            Message('user-original', Role.USER, '¿Qué incluye Grafismo Fonético?', CATALOG.generated_at),
            Message(
                'assistant-original',
                Role.ASSISTANT,
                previous_answer,
                CATALOG.generated_at,
                AnswerDetails(products=(reference,)),
            ),
        )
        turn = Turn(
            active,
            PriceStatus.VERIFIED,
            history,
            'Compara Grafismo Fonético con la Guía de Alimentación para Bebés.',
            'home',
            'synthetic',
        )
        provider = ScriptedProvider()
        composer = GraphAnswerComposer(
            GroundedComposer(provider, ComposerSettings(4000, 40000)),
            PublicRetrieval(product_only=product_only),
            24000,
        )
        prepared = composer.prepare(turn)
        events = [event async for event in composer.compose(prepared)]
        assert sum(isinstance(event, DraftEvent) for event in events) == 1
        assert len(provider.calls) == provider.closed == 1
        request = provider.calls[0]
        assert request.size_bytes() <= 24000
        payloads = {
            item.text.split(':\n', 1)[0]: json.loads(item.text.split(':\n', 1)[1]) for item in request.inputs
        }
        context = payloads['visitor_turn']
        assert context['question'] == turn.question
        assert context['conversation'][0]['text'] == history[0].content
        assert context['conversation'][1]['referenced_ids'] == [product.id]
        assert [item['role'] for item in context['conversation']] == ['user', 'assistant']
        assert history[1].content == previous_answer and turn.history == history
        mandatory = {
            doc.id for doc in CATALOG.documents if doc.kind in (DocumentKind.POLICY, DocumentKind.SUPPORT)
        }
        assert mandatory <= {item['id'] for item in decode_documents(payloads['store_data']['documents'])}
        passages = payloads.get('retrieved_public_data', {}).get('passages', [])
        if product_only:
            assert isinstance(prepared, GraphPrepared) and prepared.catalog_only
            assert not passages and prepared.sent_chunk_ids == ()
            assert {p['id'] for p in payloads['store_data']['products']} == {p.id for p in CATALOG.products}
            assert prepared.retrieval is not None and len(prepared.retrieval.chunks) == 2
        else:
            assert passages
        for item in passages:
            assert hashlib.sha256(item['text'].encode()).hexdigest() == item['sha256']
        assert isinstance(prepared, GraphPrepared)
        assert prepared.sent_chunk_ids == tuple(item['id'] for item in passages)

    asyncio.run(scenario())


@pytest.mark.parametrize('input_limit', [0, 8000])
def test_catalog_only_never_overrides_a_smaller_input_limit_or_dispatches_an_oversized_baseline(
    input_limit: int,
) -> None:
    async def scenario() -> None:
        active = ActiveCatalog(
            CATALOG, hashlib.sha256(CATALOG_BYTES).hexdigest(), CATALOG.generated_at, timedelta(hours=168)
        )
        provider = ScriptedProvider()
        composer = GraphAnswerComposer(
            GroundedComposer(provider, ComposerSettings(4000, 40000)),
            PublicRetrieval(product_only=True),
            24000,
        )
        turn = Turn(
            active,
            PriceStatus.VERIFIED,
            (),
            'Compara Grafismo Fonético con la Guía de Alimentación para Bebés.',
            'home',
            'synthetic',
        )
        prepared = composer.prepare(replace(turn, input_size_limit=input_limit))
        assert isinstance(prepared, GraphPrepared)
        assert prepared.baseline.input_size_bytes > input_limit
        with pytest.raises(GenerationError) as error:
            _ = [event async for event in composer.compose(prepared)]
        assert error.value.code is FailureCode.INVALID_REQUEST
        assert error.value.usage is not None and error.value.usage.input_tokens == 0
        assert provider.calls == [] and not prepared.catalog_only
        assert prepared.retrieval is not None

    asyncio.run(scenario())
