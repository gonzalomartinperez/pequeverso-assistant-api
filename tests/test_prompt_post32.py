"""Real final-price and catalog-hint boundaries; no model quality claim."""

from datetime import timedelta

import pytest

from app.adapters.catalog_schema import CatalogParser
from app.application.answers import answer_rules, finalize
from app.application.ports import Draft, DraftReference
from app.domain.catalog import ActiveCatalog, PriceStatus, mentioned_products
from app.domain.conversation import Notice
from tests.support import CATALOG_BYTES


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
