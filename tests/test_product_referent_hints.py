"""Product intent stays separate from navigation hints in the actual model request."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import timedelta

import pytest

from app.adapters.catalog_schema import CatalogParser
from app.ai.composer import ComposerSettings, GroundedComposer
from app.application.answers import product_ref
from app.application.ports import Turn
from app.domain.catalog import ActiveCatalog, PriceStatus, mentioned_products
from app.domain.conversation import AnswerDetails, Message, Role
from app.domain.visitor_context import VisitorContext
from tests.support import CATALOG_BYTES, ScriptedProvider

CATALOG = CatalogParser(frozenset({'pequeverso.com', 'consumer.hotmart.com', 'refund.hotmart.com'}))(
    CATALOG_BYTES
)


@pytest.mark.parametrize(
    'question',
    [
        '¿Cuánto dura el curso?',
        '¿Se pueden descargar los vídeos?',
        'Does the video course include recordings?',
        '¿Qué menú incluye?',
        'Does it include recipes?',
    ],
)
def test_format_and_food_intent_identify_the_catalog_product(question: str) -> None:
    assert mentioned_products(question, CATALOG) == frozenset({'alimentacion-bebe'})


def test_format_alias_requires_the_actual_catalog_format() -> None:
    other_format = replace(
        CATALOG,
        products=tuple(
            replace(p, format='Audio descargable') if p.id == 'alimentacion-bebe' else p
            for p in CATALOG.products
        ),
    )
    assert not mentioned_products('¿Cuánto dura el curso en vídeo?', other_format)


@pytest.mark.parametrize('path', ['/', '/grafismo-fonetico/', '/soporte/'])
@pytest.mark.parametrize(
    ('question', 'ids'),
    [
        ('¿Cómo son las clases del curso?', ['alimentacion-bebe']),
        ('¿Qué incluye el kit?', ['grafismo-fonetico']),
        ('¿Qué incluye?', []),
    ],
)
def test_serialized_referents_follow_question_not_page(path: str, question: str, ids: list[str]) -> None:
    active = ActiveCatalog(
        CATALOG, hashlib.sha256(CATALOG_BYTES).hexdigest(), CATALOG.generated_at, timedelta(hours=168)
    )
    context = VisitorContext(current_path=path)
    turn = Turn(active, PriceStatus.VERIFIED, (), question, 'product', 'synthetic', context=context)
    composer = GroundedComposer(ScriptedProvider(), ComposerSettings(4000, 40000))
    prepared = composer.prepare(turn)
    visitor = next(
        json.loads(i.text.removeprefix('visitor_turn:\n'))
        for i in prepared.request.inputs
        if i.text.startswith('visitor_turn:\n')
    )
    assert visitor['product_reference_hints'] == {
        'ids': ids,
        'basis': 'current_question' if ids else 'unresolved',
    }
    assert visitor['visitor_context']['current_path'] == path
    if len(path) > 1:
        assert path not in prepared.request.instructions
    assert prepared.input_size_bytes <= 24000
    store = next(
        json.loads(i.text.removeprefix('store_data:\n'))
        for i in prepared.request.inputs
        if i.text.startswith('store_data:\n')
    )
    assert {p['id'] for p in store['products']} == {'grafismo-fonetico', 'alimentacion-bebe'}
    assert next(p for p in store['products'] if p['id'] == 'alimentacion-bebe')['price'] is None


@pytest.mark.parametrize(
    ('question', 'expected', 'basis'),
    [
        ('¿Cuánto dura el curso?', ['alimentacion-bebe'], 'current_question'),
        ('¿Cómo lo recibo?', ['grafismo-fonetico'], 'conversation'),
        ('No quiero vídeos, prefiero PDF.', ['alimentacion-bebe', 'grafismo-fonetico'], 'current_question'),
    ],
)
def test_current_intent_overrides_history_but_hints_do_not_resolve_negation(
    question: str, expected: list[str], basis: str
) -> None:
    active = ActiveCatalog(
        CATALOG, hashlib.sha256(CATALOG_BYTES).hexdigest(), CATALOG.generated_at, timedelta(hours=168)
    )
    reference = product_ref(active, CATALOG.products[0], PriceStatus.VERIFIED)
    previous = Message(
        'previous',
        Role.ASSISTANT,
        'Sobre el kit.',
        CATALOG.generated_at,
        AnswerDetails(products=(reference,)),
    )
    turn = Turn(active, PriceStatus.VERIFIED, (previous,), question, 'product', 'synthetic')
    prepared = GroundedComposer(ScriptedProvider(), ComposerSettings(4000, 40000)).prepare(turn)
    visitor = next(
        json.loads(i.text.removeprefix('visitor_turn:\n'))
        for i in prepared.request.inputs
        if i.text.startswith('visitor_turn:\n')
    )
    assert visitor['product_reference_hints'] == {'ids': expected, 'basis': basis}
    assert visitor['conversation'][0]['referenced_ids'] == ['grafismo-fonetico']
    assert turn.history == (previous,)
    assert prepared.input_size_bytes <= 24000


def test_format_shared_by_two_products_keeps_both_as_candidates() -> None:
    both_courses = replace(
        CATALOG, products=tuple(replace(p, format='Curso en video') for p in CATALOG.products)
    )
    assert mentioned_products('¿Cómo es el curso?', both_courses) == frozenset(p.id for p in CATALOG.products)
