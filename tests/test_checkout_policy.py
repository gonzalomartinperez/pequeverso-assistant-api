"""Checkout grouping is not inferred from multiple product destinations."""

from dataclasses import replace
from datetime import timedelta

import pytest

from app.adapters.catalog_schema import CatalogParser
from app.application.answers import ValidatedStreamPrefix, answer_rules, finalize
from app.application.ports import Draft
from app.domain.answer_policy import Violation
from app.domain.catalog import ActiveCatalog, PriceStatus
from app.domain.conversation import Notice
from tests.support import CATALOG_BYTES

CATALOG = CatalogParser(frozenset({'pequeverso.com', 'consumer.hotmart.com', 'refund.hotmart.com'}))(
    CATALOG_BYTES
)


@pytest.mark.parametrize(
    'text',
    [
        'Cada compra se realiza por separado.',
        'Debes pagar los productos individualmente.',
        'Los productos no se pueden comprar juntos.',
        'No puedes combinar los dos productos en un carrito.',
        'Each purchase is completed separately.',
        'You must buy the products one at a time.',
        'The products cannot be purchased together.',
        'Both products can share a single checkout.',
        'Puedes pagar ambos productos en un único pago.',
        'Both products cost US$14.99 in a single payment.',
        'No puedo confirmarlo, pero las compras se pagan por separado.',
    ],
)
def test_unpublished_checkout_grouping_is_replaced_before_streaming(text: str) -> None:
    active = ActiveCatalog(CATALOG, 'sha', CATALOG.generated_at, timedelta(hours=168))
    rules = answer_rules(CATALOG, PriceStatus.VERIFIED, ())
    result = finalize(Draft(text, (), (), ()), active, PriceStatus.VERIFIED, rules)
    assert Notice.ANSWER_REPLACED in result.details.notices
    assert Violation.UNSUPPORTED_POLICY_CLAIM in result.violations
    stream = ValidatedStreamPrefix()
    assert stream.feed(text + ' ', CATALOG, rules) == ''


@pytest.mark.parametrize(
    'text',
    [
        'No puedo agregar productos a tu carrito ni realizar compras.',
        'I cannot add both products to your cart or buy them for you.',
        'No puedo confirmar si las compras se realizan por separado.',
        'I do not know whether the products can be purchased together.',
        'El pago se hace en la página segura de Hotmart.',
        'El kit se paga en un único pago.',
        'The kit costs US$14.99 in a single payment.',
        'El kit incluye ocho bonos; los bonos no se pagan aparte.',
        'Puedes elegir una hoja y practicar por separado los sonidos.',
    ],
)
def test_refusals_uncertainty_and_published_non_checkout_facts_remain_valid(text: str) -> None:
    active = ActiveCatalog(CATALOG, 'sha', CATALOG.generated_at, timedelta(hours=168))
    result = finalize(
        Draft(text, (), (), ()),
        active,
        PriceStatus.VERIFIED,
        answer_rules(CATALOG, PriceStatus.VERIFIED, ()),
    )
    assert result.details.notices == ()
    assert result.content == text


def test_explicit_catalog_checkout_policy_is_authority_not_the_number_of_links() -> None:
    text = 'Each purchase is completed separately.'
    document = replace(CATALOG.documents[0], text=text)
    catalog = replace(CATALOG, documents=(*CATALOG.documents, document))
    active = ActiveCatalog(catalog, 'sha', catalog.generated_at, timedelta(hours=168))
    result = finalize(
        Draft(text, (), (), ()),
        active,
        PriceStatus.VERIFIED,
        answer_rules(catalog, PriceStatus.VERIFIED, ()),
    )
    assert result.details.notices == ()
    assert result.content == text


@pytest.mark.parametrize(
    'authority',
    [
        'No puedo confirmar si las compras se realizan por separado.',
        'Los productos no se pueden comprar juntos.',
    ],
)
def test_uncertainty_or_opposite_policy_does_not_authorize_separate_purchase_claim(
    authority: str,
) -> None:
    document = replace(CATALOG.documents[0], text=authority)
    catalog = replace(CATALOG, documents=(*CATALOG.documents, document))
    active = ActiveCatalog(catalog, 'sha', catalog.generated_at, timedelta(hours=168))
    result = finalize(
        Draft('Cada compra se realiza por separado.', (), (), ()),
        active,
        PriceStatus.VERIFIED,
        answer_rules(catalog, PriceStatus.VERIFIED, ()),
    )
    assert Notice.ANSWER_REPLACED in result.details.notices
    assert Violation.UNSUPPORTED_POLICY_CLAIM in result.violations


@pytest.mark.parametrize(
    'text',
    [
        'No se venden aparte.',
        'Los bonos no se venden por separado.',
        'Los bonos solo se venden junto al material principal.',
        'Bonuses are not sold separately.',
        'Not sold separately.',
    ],
)
def test_inclusion_does_not_establish_a_separate_sale_prohibition(text: str) -> None:
    active = ActiveCatalog(CATALOG, 'sha', CATALOG.generated_at, timedelta(hours=168))
    rules = answer_rules(CATALOG, PriceStatus.VERIFIED, ())
    result = finalize(Draft(text, (), (), ()), active, PriceStatus.VERIFIED, rules)
    assert Notice.ANSWER_REPLACED in result.details.notices
    assert Violation.UNSUPPORTED_POLICY_CLAIM in result.violations
    assert ValidatedStreamPrefix().feed(text + ' ', CATALOG, rules) == ''


def test_published_inclusion_and_no_extra_payment_remain_valid() -> None:
    document = CATALOG.document('faq.grafismo-fonetico.05')
    assert document is not None
    text = document.text
    active = ActiveCatalog(CATALOG, 'sha', CATALOG.generated_at, timedelta(hours=168))
    result = finalize(
        Draft(text, (), (), ()),
        active,
        PriceStatus.VERIFIED,
        answer_rules(CATALOG, PriceStatus.VERIFIED, ()),
    )
    assert result.details.notices == ()
    assert result.content == text


def test_real_recommendation_single_product_payment_remains_valid() -> None:
    from app.application.ports import DraftReference

    text = 'El kit cuesta US$14,99 en un único pago; Hotmart lo convierte a tu moneda local.'
    active = ActiveCatalog(CATALOG, 'sha', CATALOG.generated_at, timedelta(hours=168))
    result = finalize(
        Draft(text, (DraftReference('product', 'grafismo-fonetico'),), (), ()),
        active,
        PriceStatus.VERIFIED,
        answer_rules(CATALOG, PriceStatus.VERIFIED, ()),
    )
    assert result.details.notices == ()
    assert result.content == text
    assert tuple(product.id for product in result.details.products) == ('grafismo-fonetico',)
