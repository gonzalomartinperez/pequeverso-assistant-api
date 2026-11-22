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
        ("La garantía es de una semana desde la compra.", True),
        ("El plazo para pedir el reembolso por Hotmart es de 7 días desde la compra.", True),
        ("Para pedir el reembolso, usa tu número de transacción, que empieza con HP.", True),
        ("Sobre el reembolso el productor responde en hasta 5 días.", True),
        ("La aprobación del reembolso puede tardar hasta siete días.", True),
        ("El reembolso en tarjeta de crédito puede tardar hasta 90 días.", True),
        ("La devolución por transferencia bancaria puede tardar un mes.", True),
        ("La devolución por tarjeta de crédito puede tardar tres meses.", True),
        ("El reembolso por PayPal suele verse en el resumen actual o el siguiente.", True),
        ("Si compras desde Argentina, puedes pedir el reembolso en 10 días por retracto.", True),
        ("La devolución por desistimiento en Argentina se puede solicitar en 10 días.", True),
        (
            "7 días de garantía y también la devolución del dinero en 10 días si te arrepientes",
            True,
        ),
        ("The refund can take up to 30 days by bank transfer.", True),
        ("A refund request can be approved within 5 days.", True),
        ("You have a one-week guarantee from the date of purchase.", True),
        ("El kit incluye 30 días de garantía.", False),
        ("El kit tiene una garantía de 14 días.", False),
        ("Puedes pedir el reembolso dentro de 10 días.", False),
        ("La garantía dura treinta días.", False),
        ("El reembolso por transferencia puede tardar hasta 60 días.", False),
        ("El productor responde sobre el reembolso en 6 días.", False),
        ("The refund can take up to 60 days by bank transfer.", False),
        ("The refund may be approved within 20 days.", False),
        ("Por retracto puedes pedir el reembolso dentro de catorce días.", False),
        ("Tienes una garantía de un mes.", False),
        ("Tienes una garantía de dos semanas.", False),
        ("La garantía dura cuarenta días.", False),
        ("La garantía dura veinte días.", False),
        ("El reembolso por transferencia puede tardar veintiún días.", False),
        ("El reembolso puede tardar veintiuno días.", False),
        ("You have a four-week guarantee.", False),
        ("You have a five-day guarantee.", False),
        ("You have a six-day guarantee.", False),
        ("You have an eight-day guarantee.", False),
        ("You have a nine-month guarantee.", False),
        ("You have a twenty-day guarantee.", False),
        ("No olvides la garantía de un mes.", False),
        ("No hay garantía de 30 días, pero tienes una garantía de dos semanas.", False),
        ("No hay garantía pero ofrecemos una garantía de un mes.", False),
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


@pytest.mark.parametrize(
    "text",
    [
        "No tenemos una garantía de 30 días. La garantía publicada es de 7 días.",
        "No hay garantía de 30 días. Tienes 7 días desde la compra.",
        "No ofrecemos una garantía de 30 días. Tienes 7 días desde la compra.",
        "Sin garantía de 30 días, puedes pedir el reembolso dentro de 7 días.",
        "Si hubiera una garantía de 30 días, aparecería en el catálogo.",
        # The guarantee.days eval grader can bridge sentences. Runtime validation
        # keeps the separate download or activity duration out of the guarantee claim.
        "Incluye garantía. La descarga está disponible por 30 días.",
        "Con garantía, recibes el enlace de descarga en 2 días.",
        "Tienes garantía. Puedes completar la actividad en 10 días.",
        "El producto tiene garantía. Es un plan de 30 días de actividades.",
        "Incluye garantía; la descarga está disponible por 30 días.",
        "Incluye garantía\nLa descarga está disponible por 30 días.",
    ],
)
def test_finalize_keeps_denials_and_unrelated_durations(text: str) -> None:
    result = finalize(Draft(text, (), (), ()), ACTIVE, PriceStatus.VERIFIED, RULES)
    assert result.content == text
    assert result.violations == ()


def test_stream_can_block_before_final_answer_supplies_processing_context() -> None:
    prefix = ValidatedStreamPrefix()
    first = "El reembolso puede tomar hasta 30 días."
    rest = " Ese plazo aplica por transferencia bancaria."

    assert prefix.feed(first + " ", CATALOG, RULES) == ""
    assert prefix.feed(rest.lstrip(), CATALOG, RULES) == ""

    result = finalize(Draft(first + rest, (), (), ()), ACTIVE, PriceStatus.VERIFIED, RULES)
    assert result.content == first + rest
    assert result.violations == ()
    assert prefix.finish(result) == ""


def test_finalize_reads_windows_from_active_catalog() -> None:
    policy_text = {
        "policy.guarantee": "El reembolso por transferencia puede tardar hasta 21 días.",
        "policy.withdrawal-ar": "Puedes revocar la compra dentro de 14 días.",
    }
    catalog = replace(
        CATALOG,
        products=tuple(replace(product, guarantee_days=11) for product in CATALOG.products),
        documents=tuple(
            replace(doc, text=policy_text[doc.id]) if doc.id in policy_text else doc
            for doc in CATALOG.documents
        ),
    )
    active = replace(ACTIVE, catalog=catalog)
    rules = answer_rules(catalog, PriceStatus.VERIFIED, ())

    for text in (
        "Puedes pedir el reembolso dentro de 11 días.",
        "El reembolso por transferencia puede tardar hasta 21 días.",
        "El reembolso por retracto se puede solicitar en catorce días.",
    ):
        assert (
            finalize(Draft(text, (), (), ()), active, PriceStatus.VERIFIED, rules).content == text
        )

    for text in (
        "El reembolso por retracto se puede solicitar en 10 días.",
        "El reembolso por transferencia puede tardar hasta 30 días.",
    ):
        result = finalize(Draft(text, (), (), ()), active, PriceStatus.VERIFIED, rules)
        assert result.content == REPLACEMENT_ANSWER
        assert Violation.UNSUPPORTED_GUARANTEE_CLAIM in result.violations
