"""Prompt constraints plus the unchanged final-price boundary; no model quality claim."""

from datetime import timedelta

import pytest

from app.adapters.catalog_schema import CatalogParser
from app.ai.prompt import INSTRUCTIONS, PROMPT_VERSION
from app.application.answers import answer_rules, finalize
from app.application.ports import Draft, DraftReference
from app.domain.catalog import ActiveCatalog, PriceStatus, mentioned_products
from app.domain.conversation import Notice
from tests.support import CATALOG_BYTES


def test_unknown_price_instruction_avoids_echoing_unverified_numbers() -> None:
    assert 'Do not repeat its numeric amount' in INSTRUCTIONS
    assert 'cannot confirm OR deny' in INSTRUCTIONS


def test_nonshopping_answers_use_help_without_product_cards() -> None:
    assert 'For clinical/safety, support or refund replies, omit product/resource references' in INSTRUCTIONS
    assert 'relevant supplied help links/sources' in INSTRUCTIONS


def test_unresolved_hints_cannot_be_resolved_by_navigation() -> None:
    assert 'Only when question/history leave products unclear' in INSTRUCTIONS
    assert 'Honor explicit comparisons and negated preferences even with multiple hints.' in INSTRUCTIONS
    assert 'ask which or distinguish possibilities' in INSTRUCTIONS
    assert 'never resolve ambiguity from opened_path' in INSTRUCTIONS
    assert PROMPT_VERSION == '2026-10-18.2'


@pytest.mark.parametrize(
    ('text', 'replaced'),
    [
        ('No puedo confirmar si cuesta US$19,50; consulta el precio actual en Hotmart.', True),
        ('No puedo confirmar ese importe; consulta el precio actual en Hotmart.', False),
        ('I cannot confirm US$19.50; check the current price on Hotmart.', True),
        ('I cannot confirm that amount; check the current price on Hotmart.', False),
    ],
)
def test_unknown_price_echo_and_non_echo_follow_the_same_existing_final_policy(
    text: str, replaced: bool
) -> None:
    catalog = CatalogParser(frozenset({'pequeverso.com', 'consumer.hotmart.com', 'refund.hotmart.com'}))(
        CATALOG_BYTES
    )
    active = ActiveCatalog(catalog, 'sha', catalog.generated_at, timedelta(hours=168))
    result = finalize(
        Draft(text, (DraftReference('product', 'alimentacion-bebe'),), (), ()),
        active,
        PriceStatus.VERIFIED,
        answer_rules(catalog, PriceStatus.VERIFIED, ()),
    )
    assert (Notice.ANSWER_REPLACED in result.details.notices) is replaced
    if not replaced:
        assert result.content.startswith(text)
        assert tuple(product.id for product in result.details.products) == ('alimentacion-bebe',)


@pytest.mark.parametrize(
    'question',
    [
        'Compare the video course with the PDF kit.',
        'No quiero vídeos, prefiero PDF.',
    ],
)
def test_multiple_catalog_hints_keep_comparison_and_negation_available(question: str) -> None:
    catalog = CatalogParser(frozenset({'pequeverso.com', 'consumer.hotmart.com', 'refund.hotmart.com'}))(
        CATALOG_BYTES
    )
    assert mentioned_products(question, catalog) == frozenset(p.id for p in catalog.products)
    assert 'Honor explicit comparisons and negated preferences' in INSTRUCTIONS
