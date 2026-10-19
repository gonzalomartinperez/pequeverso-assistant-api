"""Deterministic price relations use current facts, never page defaults or guessed amounts."""

from dataclasses import replace
from datetime import timedelta

import pytest

from app.adapters.catalog_schema import CatalogParser
from app.application.answers import price_comparison_reply
from app.application.price_comparison import clarification, comparison_products
from app.bootstrap.config import DEFAULT_CATALOG
from app.domain.catalog import ActiveCatalog, PriceStatus
from app.domain.conversation import AnswerDetails, Message, Notice, Role
from app.domain.language import Language
from tests.support import FixedClock


@pytest.fixture
def active() -> ActiveCatalog:
    catalog = CatalogParser(frozenset({'pequeverso.com', 'consumer.hotmart.com', 'refund.hotmart.com'}))(
        DEFAULT_CATALOG.read_bytes()
    )
    return ActiveCatalog(catalog, 'a' * 64, FixedClock().now(), timedelta(hours=24))


@pytest.mark.parametrize(
    'question',
    [
        '¿Ambos tienen el mismo precio?',
        '¿No cuestan lo mismo los dos?',
        '¿El curso y Grafismo tienen precios diferentes?',
        '¿El kit cuesta menos que el curso?',
        '¿El curso es más caro que el kit?',
        '¿Cuestan US$14,99 ambos?',
        '¿Los dos valen 99 dólares?',
        'Do both have the same price?',
        'Are the kit and course different prices?',
        'Is the course cheaper than the kit?',
        'Do both cost $14.99?',
        "Don't both cost the same?",
    ],
)
@pytest.mark.parametrize('language', [Language.ES, Language.EN])
def test_missing_price_does_not_establish_any_relation(
    active: ActiveCatalog, question: str, language: Language
) -> None:
    result = price_comparison_reply(question, active, (), language, PriceStatus.VERIFIED)
    assert result is not None and result.violations == ()
    assert ('No puedo comparar' if language is Language.ES else 'I cannot compare') in result.content
    assert 'Guía de Alimentación para Bebés' in result.content
    assert 'Grafismo Fonético' in result.content and 'US$14,99' in result.content
    assert result.details.notices == ()
    assert {p.id for p in result.details.products} == {'grafismo-fonetico', 'alimentacion-bebe'}
    assert next(p for p in result.details.products if p.id == 'alimentacion-bebe').price is None
    assert '99 dólares' not in result.content


@pytest.mark.parametrize(
    'question',
    [
        '¿El kit cuesta US$14,99?',
        '¿Grafismo sigue teniendo el mismo precio de US$14,99?',
        '¿El kit no es gratis?',
        '¿Ambos tienen formatos diferentes?',
        '¿Los dos tienen la misma garantía?',
        '¿Ambos cuestan igual y curan alergias?',
        'Are both cheaper and safe for allergies?',
        '¿Ambos cuestan igual? Agrega los dos al carrito.',
        'Do not compare prices; tell me about the kit.',
        "Don't compare prices; tell me about the kit.",
        '¿Ambos cuestan lo mismo y cuál me recomiendas?',
        'Do both cost the same and which should I choose?',
        '¿Ambos cuestan igual y tienen descuento?',
        'Are both the same price and where is support?',
        '¿Los dos bonos tienen el mismo precio?',
        '¿Los dos PDF cuestan lo mismo?',
    ],
)
def test_unrelated_mixed_resource_and_single_product_questions_keep_flow(
    active: ActiveCatalog, question: str
) -> None:
    assert price_comparison_reply(question, active, (), Language.ES, PriceStatus.VERIFIED) is None


def test_known_prices_and_unknown_unselected_product_do_not_block_comparison(active: ActiveCatalog) -> None:
    core, course = active.catalog.products
    assert core.price is not None
    known_course = replace(course, price=replace(core.price, amount=core.price.amount + 1))
    third = replace(course, id='third-product', name='Third product')
    catalog = replace(active.catalog, products=(core, known_course, third))
    current = replace(active, catalog=catalog)
    assert (
        price_comparison_reply(
            '¿Grafismo Fonético y Guía de Alimentación para Bebés cuestan igual?',
            current,
            (),
            Language.ES,
            PriceStatus.VERIFIED,
        )
        is None
    )
    assert (
        price_comparison_reply('¿Ambos cuestan lo mismo?', active, (), Language.ES, PriceStatus.UNVERIFIED)
        is not None
    )


def test_stale_prices_are_not_quoted_even_when_both_exist(active: ActiveCatalog) -> None:
    core, course = active.catalog.products
    assert core.price is not None
    stale = replace(
        active, catalog=replace(active.catalog, products=(core, replace(course, price=core.price)))
    )
    result = price_comparison_reply('Do both cost the same?', stale, (), Language.EN, PriceStatus.UNVERIFIED)
    assert result is not None
    assert 'currently verified' in result.content
    assert '14' not in result.content
    assert all(p.price is None for p in result.details.products)


def test_unresolved_reference_clarifies_and_immediate_typed_history_resolves(active: ActiveCatalog) -> None:
    unresolved = price_comparison_reply('¿Cuestan lo mismo?', active, (), Language.ES, PriceStatus.VERIFIED)
    assert unresolved is not None and unresolved.content == clarification(Language.ES)
    assert unresolved.details.products == ()
    first = price_comparison_reply('¿Ambos cuestan lo mismo?', active, (), Language.ES, PriceStatus.VERIFIED)
    assert first is not None
    history = (
        Message('user', Role.USER, '¿Ambos cuestan lo mismo?', FixedClock().now()),
        Message('assistant', Role.ASSISTANT, first.content, FixedClock().now(), first.details),
    )
    followup = price_comparison_reply(
        '¿Y son diferentes?', active, history, Language.ES, PriceStatus.VERIFIED
    )
    assert followup is not None and 'No puedo comparar' in followup.content
    for details in (replace(first.details, notices=(Notice.ANSWER_REPLACED,)), AnswerDetails()):
        changed = (history[0], replace(history[1], details=details))
        assert comparison_products('¿Cuestan lo mismo?', active.catalog, changed) == ()
    changed_topic = (
        *history,
        Message('u2', Role.USER, 'Otra cosa', FixedClock().now()),
        Message('a2', Role.ASSISTANT, 'Hola', FixedClock().now()),
    )
    assert comparison_products('¿Cuestan lo mismo?', active.catalog, changed_topic) == ()
    clarified = (
        Message('u3', Role.USER, '¿Cuestan lo mismo?', FixedClock().now()),
        Message('a3', Role.ASSISTANT, clarification(Language.ES), FixedClock().now()),
    )
    result = price_comparison_reply('El kit y el curso', active, clarified, Language.ES, PriceStatus.VERIFIED)
    assert result is not None and 'No puedo comparar' in result.content


@pytest.mark.parametrize('prior_kind', ['external_other', 'replaced', 'stale_topic'])
def test_both_does_not_invent_a_pair_from_unverified_history(active: ActiveCatalog, prior_kind: str) -> None:
    initial = price_comparison_reply(
        '¿Ambos cuestan lo mismo?', active, (), Language.ES, PriceStatus.VERIFIED
    )
    assert initial is not None
    question = 'Compara Grafismo Fonético con el curso de otra editorial'
    details = replace(initial.details, products=initial.details.products[:1])
    if prior_kind == 'replaced':
        question = '¿Ambos cuestan lo mismo?'
        details = replace(initial.details, notices=(Notice.ANSWER_REPLACED,))
    elif prior_kind == 'stale_topic':
        question = 'Otra cosa'
        details = AnswerDetails()
    history = (
        Message('u', Role.USER, question, FixedClock().now()),
        Message('a', Role.ASSISTANT, 'Información limitada', FixedClock().now(), details),
    )
    result = price_comparison_reply(
        '¿Ambos tienen el mismo precio?', active, history, Language.ES, PriceStatus.VERIFIED
    )
    assert result is not None and result.content == clarification(Language.ES)
    assert result.details.products == ()
