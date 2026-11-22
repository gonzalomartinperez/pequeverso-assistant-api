from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

from app.adapters.catalog_schema import CatalogParser
from app.application.answers import (
    REPLACEMENT_ANSWER,
    ValidatedStreamPrefix,
    answer_rules,
    finalize,
)
from app.application.ports import Draft, DraftReference
from app.domain.answer_policy import Violation
from app.domain.catalog import ActiveCatalog, PriceStatus
from app.domain.conversation import Notice

CATALOG = CatalogParser(
    frozenset({"pequeverso.com", "consumer.hotmart.com", "refund.hotmart.com"})
)((Path(__file__).resolve().parents[1] / "catalog" / "catalog.v1.json").read_bytes())
ACTIVE = ActiveCatalog(CATALOG, "sha", CATALOG.generated_at, timedelta(days=7))
RULES = answer_rules(CATALOG, PriceStatus.VERIFIED, ())


@pytest.mark.parametrize(
    ("text", "supported"),
    [
        ("Tienes 7 días de garantía.", True),
        ("En Argentina puedes revocar la compra y pedir el reembolso dentro de 10 días.", True),
        ("El reembolso por transferencia puede tardar hasta 30 días.", True),
        ("La garantía dura siete días.", True),
        ("El kit incluye 30 días de garantía.", False),
        ("El kit tiene una garantía de 14 días.", False),
        ("Puedes pedir el reembolso dentro de 10 días.", False),
        ("La garantía dura treinta días.", False),
        ("El reembolso por transferencia puede tardar hasta 60 días.", False),
    ],
)
def test_finalize_guarantee_window(text: str, supported: bool) -> None:
    result = finalize(
        Draft(text, (DraftReference("product", "grafismo-fonetico"),), (), ()),
        ACTIVE,
        PriceStatus.VERIFIED,
        RULES,
    )

    if supported:
        assert result.content == text
        assert result.violations == ()
        assert result.details.notices == ()
    else:
        assert result.content == REPLACEMENT_ANSWER
        assert Violation.UNSUPPORTED_GUARANTEE_CLAIM in result.violations
        assert result.details.notices == (Notice.ANSWER_REPLACED,)
        assert result.details.products == ()


def test_stream_stops_at_unsupported_guarantee_window() -> None:
    prefix = ValidatedStreamPrefix()
    safe_text = "El kit es digital."

    assert prefix.feed(safe_text + " ", CATALOG, RULES) == safe_text
    assert prefix.feed("La garantía dura treinta días. ", CATALOG, RULES) == ""


def test_finalize_reads_windows_from_active_catalog() -> None:
    policy = CATALOG.document("policy.guarantee")
    assert policy is not None
    catalog = replace(
        CATALOG,
        products=tuple(replace(product, guarantee_days=11) for product in CATALOG.products),
        documents=tuple(
            replace(doc, text="El reembolso por transferencia puede tardar hasta 21 días.")
            if doc == policy
            else doc
            for doc in CATALOG.documents
        ),
    )
    active = replace(ACTIVE, catalog=catalog)
    rules = answer_rules(catalog, PriceStatus.VERIFIED, ())

    for text in (
        "Puedes pedir el reembolso dentro de 11 días.",
        "El reembolso por transferencia puede tardar hasta 21 días.",
    ):
        assert (
            finalize(Draft(text, (), (), ()), active, PriceStatus.VERIFIED, rules).content == text
        )
