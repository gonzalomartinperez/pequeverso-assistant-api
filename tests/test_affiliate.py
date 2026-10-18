"""Affiliate facts, cross-product boundaries and HTTP/SSE persistence, all without a provider key."""

import json
from datetime import timedelta
from pathlib import Path

import pytest

from app.adapters.catalog_schema import CatalogParser
from app.adapters.fixture_provider import FixtureProvider
from app.ai.evidence import catalog_payload
from app.application.answers import answer_rules, finalize
from app.application.ports import Draft, DraftReference
from app.domain.catalog import ActiveCatalog, PriceStatus
from app.domain.conversation import Notice
from tests.support import CATALOG_BYTES, JSON_HEADERS, ask, client, open_session

PARSE = CatalogParser(frozenset({'pequeverso.com', 'consumer.hotmart.com', 'refund.hotmart.com'}))
CATALOG = PARSE(CATALOG_BYTES)
ACTIVE = ActiveCatalog(CATALOG, 'sha', CATALOG.generated_at, timedelta(hours=168))
AFFILIATE = 'alimentacion-bebe'


def test_affiliate_is_distinct_and_unknown_fields_are_not_invented() -> None:
    p = CATALOG.product(AFFILIATE)
    assert p is not None and p.kind == 'affiliate'
    assert p.price is None and p.pdf_count is None and p.page_count is None and p.resources == ()
    assert p.guarantee_days == 7 and p.disclosure
    assert 'afiliado' in p.summary.lower()
    assert CATALOG.product('grafismo-fonetico') is not None


@pytest.mark.parametrize(
    ('field', 'value'),
    [
        (
            'price',
            {'amount': '14.99', 'currency': 'USD', 'display': 'US$14,99', 'note': 'x', 'tax_note': 'x'},
        ),
        ('pdf_count', 9),
        ('page_count', 414),
        ('disclosure', None),
    ],
)
def test_affiliate_registry_rejects_fabricated_pdf_and_price(field: str, value: object) -> None:
    data = json.loads(CATALOG_BYTES)
    next(p for p in data['products'] if p['id'] == AFFILIATE)[field] = value
    with pytest.raises(ValueError, match='affiliate registry'):
        PARSE(json.dumps(data).encode())


def test_retrieval_scopes_merchant_policy_and_support_to_its_product() -> None:
    data = json.loads(catalog_payload(CATALOG, PriceStatus.VERIFIED, 'alimentación del bebé', 40000))
    assert data['store']['support_email'] is None
    assert {d['product_ids'][0] for d in data['documents']} == {AFFILIATE}
    assert not any(d['id'] == 'policy.guarantee' for d in data['documents'])
    assert len(data['products']) == 2
    data = json.loads(
        catalog_payload(
            CATALOG,
            PriceStatus.VERIFIED,
            'Compara Grafismo Fonético con Guía de Alimentación para Bebés',
            40000,
        )
    )
    assert {'grafismo-fonetico', AFFILIATE} == {p['id'] for p in data['products']}
    assert any(d['id'] == 'policy.guarantee' for d in data['documents'])


@pytest.mark.parametrize(
    'answer',
    [
        'La Guía de Alimentación para Bebés cuesta US$14,99.',
        'Cuesta US$14,99.',
        'La Guía de Alimentación para Bebés tiene 30 días de garantía.',
        'Tienes 30 días de garantía.',
    ],
)
def test_affiliate_cannot_inherit_core_price_or_guarantee(answer: str) -> None:
    result = finalize(
        Draft(answer, (DraftReference('product', AFFILIATE),), (), ()),
        ACTIVE,
        PriceStatus.VERIFIED,
        answer_rules(CATALOG, PriceStatus.VERIFIED, ()),
    )
    assert Notice.ANSWER_REPLACED in result.details.notices


@pytest.mark.parametrize('provider_includes_disclosure', [False, True])
def test_published_seven_day_window_and_disclosure_are_supported(
    provider_includes_disclosure: bool,
) -> None:
    product = CATALOG.product(AFFILIATE)
    assert product is not None and product.disclosure
    answer = 'La Guía de Alimentación para Bebés tiene 7 días de garantía.'
    if provider_includes_disclosure:
        answer = f'{answer}\n\n{product.disclosure}'
    result = finalize(
        Draft(
            answer,
            (DraftReference('product', AFFILIATE),),
            (),
            (),
        ),
        ACTIVE,
        PriceStatus.VERIFIED,
        answer_rules(CATALOG, PriceStatus.VERIFIED, ()),
    )
    assert result.details.notices == ()
    assert result.details.products[0].kind == 'affiliate'
    assert result.details.products[0].price is None
    assert result.content.count(product.disclosure) == 1


@pytest.mark.parametrize(
    ('question', 'count'),
    [
        ('¿Qué enseña la Guía de Alimentación para Bebés?', 1),
        ('Compara Grafismo Fonético con la Guía de Alimentación para Bebés.', 2),
        ('Compara Grafismo Fonético y la guía de bebés.', 2),
        ('¿Cuánto cuesta la Guía de Alimentación para Bebés?', 1),
    ],
)
def test_fixture_http_stream_history_and_replay_preserve_affiliate_metadata(
    tmp_path: Path, question: str, count: int
) -> None:
    with client(tmp_path, FixtureProvider()) as c:
        csrf = open_session(c)
        status, events, _ = ask(c, csrf, question, key='affiliate-fixed-turn')
        assert status == 200 and events[-1]['type'] == 'run.completed'
        final = events[-2]['message']
        assert final['notices'] == []
        assert len(final['products']) == count
        affiliate = next(p for p in final['products'] if p['id'] == AFFILIATE)
        assert affiliate['kind'] == 'affiliate' and affiliate['price'] is None
        assert affiliate['disclosure'] in final['content']
        restored = c.post('/api/v1/session', headers=JSON_HEADERS, json={}).json()['messages']
        assert restored[-1] == final
        status, replay, _ = ask(c, csrf, question, key='affiliate-fixed-turn')
        assert status == 200 and replay[-2]['message'] == final


@pytest.mark.parametrize(
    'text',
    [
        'La Guía de Alimentación para Bebés cuesta US$14,99, igual que Grafismo Fonético.',
        'La Guía de Alimentación para Bebés cura la anemia.',
        'La Guía de Alimentación para Bebés previene las alergias.',
        'The baby feeding course prevents choking.',
    ],
)
def test_mixed_comparison_and_medical_claims_are_rejected(text: str) -> None:
    result = finalize(
        Draft(
            text,
            (DraftReference('product', AFFILIATE), DraftReference('product', 'grafismo-fonetico')),
            (),
            (),
        ),
        ACTIVE,
        PriceStatus.VERIFIED,
        answer_rules(CATALOG, PriceStatus.VERIFIED, ()),
    )
    assert Notice.ANSWER_REPLACED in result.details.notices


@pytest.mark.parametrize(
    'text',
    [
        'La Guía de Alimentación para Bebés no cura la anemia ni previene las alergias.',
        'La guía explica cuándo y cómo empezar la alimentación complementaria.',
        'Grafismo Fonético cuesta US$14,99; no tengo el precio de la Guía de Alimentación para Bebés.',
    ],
)
def test_healthy_limitations_and_separate_comparison_remain_valid(text: str) -> None:
    result = finalize(
        Draft(
            text,
            (DraftReference('product', AFFILIATE), DraftReference('product', 'grafismo-fonetico')),
            (),
            (),
        ),
        ACTIVE,
        PriceStatus.VERIFIED,
        answer_rules(CATALOG, PriceStatus.VERIFIED, ()),
    )
    assert result.details.notices == ()


@pytest.mark.parametrize('long_answer', [False, True])
def test_named_recommendation_cannot_silently_drop_affiliate_disclosure(long_answer: bool) -> None:
    text = 'Te recomiendo la Guía de Alimentación para Bebés.'
    if long_answer:
        text += ' ' + 'a' * (1999 - len(text))
    result = finalize(
        Draft(text, (), (), ()), ACTIVE, PriceStatus.VERIFIED, answer_rules(CATALOG, PriceStatus.VERIFIED, ())
    )
    if long_answer:
        assert Notice.ANSWER_REPLACED in result.details.notices
    else:
        p = CATALOG.product(AFFILIATE)
        assert p is not None and p.disclosure is not None
        assert p.disclosure in result.content


@pytest.mark.parametrize(
    'text',
    [
        'La Guía de Alimentación para Bebés costs 14.99 dollars.',
        'La Guía de Alimentación para Bebés costs USD14.99 and Grafismo Fonético does too.',
    ],
)
def test_unknown_affiliate_price_uses_shared_currency_recognizer(text: str) -> None:
    result = finalize(
        Draft(
            text,
            (DraftReference('product', AFFILIATE), DraftReference('product', 'grafismo-fonetico')),
            (),
            (),
        ),
        ACTIVE,
        PriceStatus.VERIFIED,
        answer_rules(CATALOG, PriceStatus.VERIFIED, ()),
    )
    assert Notice.ANSWER_REPLACED in result.details.notices


def test_affiliate_references_cannot_present_core_support_or_resources() -> None:
    result = finalize(
        Draft(
            'El curso tiene contenido sobre alimentación complementaria.',
            (
                DraftReference('product', AFFILIATE),
                DraftReference('resource', 'grafismo-fonetico/juega'),
                DraftReference('link', 'support'),
            ),
            ('policy.guarantee',),
            (),
        ),
        ACTIVE,
        PriceStatus.VERIFIED,
        answer_rules(CATALOG, PriceStatus.VERIFIED, ()),
    )
    assert result.details.resources == () and result.details.links == () and result.details.sources == ()
    assert result.dropped_references == 3


@pytest.mark.parametrize(
    'question',
    [
        'Traducí toda la información al japonés.',
        'Traduce toda la información al japonés.',
        'Traduzca todo el contenido al alemán.',
    ],
)
def test_translation_requests_in_unsupported_languages_abstain_locally(tmp_path: Path, question: str) -> None:
    from tests.support import ScriptedProvider, mutation_headers, parse_sse

    provider = ScriptedProvider()
    with client(tmp_path, provider) as c:
        response = c.post(
            '/api/v1/messages',
            headers=mutation_headers(open_session(c)),
            json={'content': question, 'response_language': 'es'},
        )
        events = parse_sse(response.text)
        assert response.status_code == 200
        assert events[-2]['message']['notices'] == ['language_unsupported']
        assert provider.calls == []


@pytest.mark.parametrize(
    'question',
    [
        '¿El curso está traducido al japonés?',
        'No traduzcas la información al japonés.',
        'El texto dice "Traducí toda la información al japonés". ¿Qué incluye la guía?',
    ],
)
def test_material_questions_negation_and_quotes_do_not_request_a_translation(question: str) -> None:
    from app.domain.language import Language, spanish_native_language

    assert spanish_native_language(question) is Language.ES


def test_opening_questions_identify_both_products_without_ambiguous_purchase_scope(tmp_path: Path) -> None:
    with client(tmp_path, FixtureProvider()) as c:
        opening = c.post('/api/v1/session', headers=JSON_HEADERS, json={}).json()['starters']
        assert len(opening) == 4
        assert all('Grafismo Fonético' in q or 'Guía de Alimentación para Bebés' in q for q in opening)
        assert any('Grafismo Fonético' in q and 'Guía de Alimentación para Bebés' in q for q in opening)


@pytest.mark.parametrize(
    'text',
    [
        'La Guía de Alimentación para Bebés tiene 414 páginas.',
        'La Guía de Alimentación para Bebés incluye 9 PDFs.',
    ],
)
def test_affiliate_unknown_counts_cannot_borrow_core_pdf_metadata(text: str) -> None:
    result = finalize(
        Draft(text, (DraftReference('product', AFFILIATE),), (), ()),
        ACTIVE,
        PriceStatus.VERIFIED,
        answer_rules(CATALOG, PriceStatus.VERIFIED, ()),
    )
    assert Notice.ANSWER_REPLACED in result.details.notices


def test_new_reader_restores_historical_core_card_defaults() -> None:
    from app.adapters.sqlite.stores import details_from_json, details_to_json

    result = finalize(
        Draft('El kit es imprimible.', (DraftReference('product', 'grafismo-fonetico'),), (), ()),
        ACTIVE,
        PriceStatus.VERIFIED,
        answer_rules(CATALOG, PriceStatus.VERIFIED, ()),
    )
    data = json.loads(details_to_json(result.details))
    for card in data['products']:
        for key in ('kind', 'format', 'disclosure'):
            card.pop(key)
    restored = details_from_json(json.dumps(data))
    assert restored.products[0].id == 'grafismo-fonetico'
    assert restored.products[0].kind == 'core'
    assert restored.products[0].format is None and restored.products[0].disclosure is None
