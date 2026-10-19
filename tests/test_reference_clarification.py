"""Current canonical identities and immediate typed options bound local clarification."""

from dataclasses import replace
from datetime import timedelta

import pytest

from app.adapters.catalog_schema import CatalogParser
from app.application.answers import answer_rules, finalize, reference_clarification_reply
from app.application.ports import Draft, DraftReference
from app.application.reference_clarification import clarification, reference_reply
from app.bootstrap.config import DEFAULT_CATALOG
from app.domain.catalog import ActiveCatalog, PriceStatus
from app.domain.conversation import AnswerDetails, Message, Notice, ReferenceKind, Role, SourceRef
from app.domain.language import Language
from tests.support import FixedClock


@pytest.fixture
def active():
    catalog = CatalogParser(frozenset({'pequeverso.com', 'consumer.hotmart.com', 'refund.hotmart.com'}))(
        DEFAULT_CATALOG.read_bytes()
    )
    return ActiveCatalog(catalog, 'a' * 64, FixedClock().now(), timedelta(hours=24))


def options(active, resources=False):
    refs = (
        tuple(
            DraftReference(ReferenceKind.RESOURCE, p)
            for p in ('grafismo-fonetico/safari', 'grafismo-fonetico/juega')
        )
        if resources
        else tuple(DraftReference(ReferenceKind.PRODUCT, p.id) for p in active.catalog.products)
    )
    answer = finalize(
        Draft('Opciones del catálogo.', refs, (), ()),
        active,
        PriceStatus.VERIFIED,
        answer_rules(active.catalog, PriceStatus.VERIFIED, ()),
        Language.ES,
    )
    return (
        Message('u', Role.USER, 'Compara las opciones', FixedClock().now()),
        Message('a', Role.ASSISTANT, answer.content, FixedClock().now(), answer.details),
    )


@pytest.mark.parametrize(
    'question',
    [
        'Ese producto, ¿se imprime?',
        '¿La guía incluye los bonos?',
        'Can that product be printed?',
        'Is that guide downloadable?',
    ],
)
def test_singular_reference_after_multiple_options_clarifies_without_topic_identity(active, question):
    result = reference_clarification_reply(
        question, active, options(active), Language.ES, PriceStatus.VERIFIED
    )
    assert result is not None and result.content == clarification(Language.ES)
    assert result.details.products == result.details.resources == ()


@pytest.mark.parametrize(
    'question',
    [
        '¿Guía de Alimentación para Bebés se imprime?',
        '¿El curso se imprime?',
        '¿El video se descarga?',
        '¿Grafismo Fonético se imprime?',
        '¿El PDF se imprime?',
        '¿El kit se imprime?',
    ],
)
def test_explicit_current_names_or_unique_published_format_do_not_clarify(active, question):
    assert reference_reply(question, active.catalog, options(active)) is None


@pytest.mark.parametrize(
    'question',
    [
        '¿Ese producto cura alergias?',
        'Buy that product now',
        'Ese producto, dame la clave',
        '¿Ese producto tiene garantía?',
    ],
)
def test_mixed_safety_transaction_and_policy_requests_retain_existing_flow(active, question):
    assert reference_reply(question, active.catalog, options(active)) is None


@pytest.mark.parametrize('change', ['none', 'single', 'replaced', 'external', 'stale'])
def test_history_must_supply_immediate_unreplaced_current_multiple_options(active, change):
    history = options(active)
    if change == 'none':
        history = ()
    if change == 'single':
        history = (
            history[0],
            replace(
                history[1], details=replace(history[1].details, products=history[1].details.products[:1])
            ),
        )
    if change == 'replaced':
        history = (
            history[0],
            replace(history[1], details=replace(history[1].details, notices=(Notice.ANSWER_REPLACED,))),
        )
    if change == 'external':
        history = (
            history[0],
            replace(
                history[1],
                details=replace(
                    history[1].details, sources=(SourceRef('external', 'Other', 'https://example.org'),)
                ),
            ),
        )
    if change == 'stale':
        history = (
            *history,
            Message('u2', Role.USER, 'Otra cosa', FixedClock().now()),
            Message('a2', Role.ASSISTANT, 'Hola', FixedClock().now()),
        )
    assert reference_reply('Ese producto, ¿se imprime?', active.catalog, history) is None


@pytest.mark.parametrize(
    'question',
    ['Me refiero a la guía de alimentación.', 'Guía de Alimentación para Bebés', 'I mean the course.'],
)
@pytest.mark.parametrize('language', [Language.ES, Language.EN])
def test_exact_immediate_name_correction_preserves_unknown_printable_extras(active, question, language):
    history = (
        Message('u', Role.USER, 'Ese producto, ¿se imprime?', FixedClock().now()),
        Message('a', Role.ASSISTANT, clarification(language), FixedClock().now()),
    )
    result = reference_clarification_reply(question, active, history, language, PriceStatus.VERIFIED)
    assert result is not None and 'video' in result.content.lower()
    assert (
        'No tengo confirmación' if language is Language.ES else 'I do not have confirmation'
    ) in result.content
    assert [p.id for p in result.details.products] == ['alimentacion-bebe']
    product = active.catalog.product('alimentacion-bebe')
    assert product is not None and product.pdf_count is None and product.page_count is None
    assert '0 PDF' not in result.content and 'no se puede imprimir' not in result.content.lower()
    for wrong in (
        replace(history[1], content='Otra respuesta'),
        replace(history[1], details=AnswerDetails(notices=(Notice.ANSWER_REPLACED,))),
    ):
        assert reference_reply(question, active.catalog, (history[0], wrong)) is None


def test_correction_with_a_new_question_does_not_drop_new_requested_details(active):
    history = (
        Message('u', Role.USER, '¿Se imprime?', FixedClock().now()),
        Message('a', Role.ASSISTANT, clarification(Language.ES), FixedClock().now()),
    )
    assert reference_reply('Me refiero al curso y dime cuántas horas tiene', active.catalog, history) is None


def test_mixed_resource_question_keeps_actual_counts_without_inventing_guide_membership(active):
    result = reference_clarification_reply(
        'Compáralos y dime si la guía los incluye.',
        active,
        options(active, resources=True),
        Language.ES,
        PriceStatus.VERIFIED,
    )
    assert result is not None and '40' in result.content and '50' in result.content
    assert result.content.endswith(clarification(Language.ES, guide=True))
    assert {r.id for r in result.details.resources} == {'grafismo-fonetico/safari', 'grafismo-fonetico/juega'}
    assert not result.details.products


@pytest.mark.parametrize('question', ['Ese producto, ¿incluye PDF?', 'Ese producto, ¿incluye video?'])
def test_requested_format_property_cannot_identify_the_ambiguous_product(active, question):
    result = reference_clarification_reply(
        question, active, options(active), Language.ES, PriceStatus.VERIFIED
    )
    assert result is not None and result.content == clarification(Language.ES)
    assert result.details.products == ()


@pytest.mark.parametrize(
    'question', ['¿Ambos productos se imprimen?', 'Can both products be printed?', 'Do they print?']
)
def test_explicit_plural_question_does_not_get_singular_clarification(active, question):
    assert reference_reply(question, active.catalog, options(active)) is None


def test_conflicting_explicit_format_qualification_keeps_ordinary_flow(active):
    assert reference_reply('¿El PDF del curso se imprime?', active.catalog, options(active)) is None


def test_pdf_property_clarification_correction_inherits_only_the_immediate_task(active):
    history = (
        Message('u', Role.USER, 'Ese producto, ¿incluye PDF?', FixedClock().now()),
        Message('a', Role.ASSISTANT, clarification(Language.ES), FixedClock().now()),
    )
    result = reference_clarification_reply(
        'Me refiero a la guía de alimentación.', active, history, Language.ES, PriceStatus.VERIFIED
    )
    assert result is not None and 'video' in result.content.lower()
    assert 'No tengo confirmación' in result.content
    assert [p.id for p in result.details.products] == ['alimentacion-bebe']
