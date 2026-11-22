"""Ordered grounding and finalization results recorded before the stage extraction."""

from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

from app.adapters.catalog_schema import CatalogParser
from app.application.answers import (
    CheckedContent,
    FinalizedAnswer,
    answer_rules,
    check_content,
    finalize,
)
from app.application.ports import Draft, DraftReference
from app.domain.answer_policy import Violation
from app.domain.catalog import ActiveCatalog, PriceStatus
from app.domain.conversation import AnswerDetails, LinkRef, Notice
from app.domain.language import Language
from app.domain.web_evidence import SOURCES, WebEvidence

CATALOG = CatalogParser(
    frozenset({"pequeverso.com", "consumer.hotmart.com", "refund.hotmart.com"})
)((Path(__file__).resolve().parents[1] / "catalog" / "catalog.v1.json").read_bytes())
ACTIVE = ActiveCatalog(CATALOG, "sha", CATALOG.generated_at, timedelta(hours=168))
RULES = answer_rules(CATALOG, PriceStatus.VERIFIED, ())


def test_content_preserves_first_violation_order_across_raw_and_readable_checks() -> None:
    checked = check_content(
        " <b>Texto</b> \ue200cite\ue202https://example.org/a\ue201. El precio es US$[5]. "
        "La Guía de Alimentación para Bebés tiene 9 PDFs. Tienes 99 días de garantía. ",
        CATALOG,
        RULES,
    )

    assert checked == CheckedContent(
        "Texto . El precio es US$5. La Guía de Alimentación para Bebés tiene 9 PDFs. "
        "Tienes 99 días de garantía.",
        (
            Violation.UNLISTED_URL,
            Violation.UNKNOWN_PRICE,
            Violation.UNSUPPORTED_PAGE_CLAIM,
            Violation.UNSUPPORTED_POLICY_CLAIM,
        ),
    )
    assert not checked.accepted


@pytest.mark.parametrize(
    ("draft_text", "readable"),
    [
        (
            "La Guía de Alimentación para Bebés \ue200cite\ue202cuesta US$14,99\ue201.",
            "La Guía de Alimentación para Bebés .",
        ),
        (
            "La Guía de Alimentación para Bebés cuesta US$[14,99].",
            "La Guía de Alimentación para Bebés cuesta US$14,99.",
        ),
    ],
)
def test_product_scope_rejects_borrowed_price_on_either_pass(
    draft_text: str, readable: str
) -> None:
    assert check_content(draft_text, CATALOG, RULES) == CheckedContent(
        readable, (Violation.UNKNOWN_PRICE,)
    )


def test_product_scope_allows_negated_pdf_count() -> None:
    text = "La Guía de Alimentación para Bebés no incluye 9 PDFs."
    checked = check_content(text, CATALOG, RULES)

    assert checked == CheckedContent(text, ())
    assert checked.accepted


def test_product_scope_cannot_borrow_a_published_policy_from_another_product() -> None:
    core_policy = CATALOG.document("policy.guarantee")
    assert core_policy is not None
    catalog = replace(
        CATALOG,
        documents=(*CATALOG.documents, replace(core_policy, text="Tienes 30 días de garantía.")),
    )
    text = "La Guía de Alimentación para Bebés tiene 30 días de garantía."
    assert check_content(text, catalog, RULES) == CheckedContent(
        text, (Violation.UNSUPPORTED_POLICY_CLAIM,)
    )
    unscoped_text = "Tienes 30 días de garantía."
    assert check_content(unscoped_text, catalog, RULES) == CheckedContent(unscoped_text, ())


def test_caps_preserve_first_seen_references_and_only_invalid_ids_count_as_dropped() -> None:
    resource_ids = (
        "grafismo-fonetico/juega",
        "grafismo-fonetico/paso-a-paso",
        "grafismo-fonetico/safari",
        "grafismo-fonetico/10-minutos",
    )
    link_ids = ("purchases-refunds", "support", "withdrawal", "product-page.grafismo-fonetico")
    delivery, refund, support = (
        WebEvidence(source, "Procedimiento publicado.", "sha", CATALOG.generated_at)
        for source in SOURCES
    )
    final = finalize(
        Draft(
            "  <b>El material es digital.</b>  ",
            (
                DraftReference("product", "grafismo-fonetico"),
                DraftReference("product", "grafismo-fonetico"),
                *(DraftReference("resource", item) for item in (resource_ids[0], *resource_ids)),
                *(DraftReference("link", item) for item in (link_ids[0], *link_ids)),
                DraftReference("resource", "grafismo-fonetico/inventado"),
            ),
            (
                delivery.id,
                delivery.id,
                "policy.payment",
                refund.id,
                support.id,
                "policy.delivery",
                "unknown",
            ),
            ("<b></b>", "a" * 91, "  ¿Qué   incluye? ", "¿Qué incluye?", "b" * 90, "¿Y?", "¿Más?"),
        ),
        ACTIVE,
        PriceStatus.VERIFIED,
        RULES,
        web_evidence=(delivery, refund, support),
        catalog_source_ids=frozenset({"policy.payment", "policy.delivery"}),
    )

    assert final.content == "El material es digital."
    assert tuple(p.id for p in final.details.products) == ("grafismo-fonetico",)
    assert tuple(r.id for r in final.details.resources) == resource_ids[:3]
    assert tuple(link.id for link in final.details.links) == link_ids[:3]
    assert tuple(source.id for source in final.details.sources) == (
        "hotmart:209033897",
        "policy.payment",
        "hotmart:360061973392",
    )
    assert final.details.follow_ups == ("¿Qué incluye?", "b" * 90, "¿Y?")
    assert final.details.notices == ()
    assert final.details.language == "es"
    assert final.violations == ()
    assert final.dropped_references == 2


def test_invalid_product_id_leaves_other_references_unscoped() -> None:
    final = finalize(
        Draft(
            "El material es digital.",
            (
                DraftReference("product", "inventado"),
                DraftReference("resource", "grafismo-fonetico/juega"),
                DraftReference("link", "support"),
            ),
            ("policy.payment",),
            (),
        ),
        ACTIVE,
        PriceStatus.VERIFIED,
        RULES,
    )

    assert final.content == "El material es digital."
    assert final.details.products == ()
    assert tuple(r.id for r in final.details.resources) == ("grafismo-fonetico/juega",)
    assert tuple(link.id for link in final.details.links) == ("support",)
    assert tuple(source.id for source in final.details.sources) == ("policy.payment",)
    assert final.dropped_references == 1


@pytest.mark.parametrize(
    ("disclosure", "violations"),
    [
        ("x" * 2000, ()),
        ("Lee https://example.org/a.", (Violation.UNLISTED_URL,)),
        ("Consulta \ue200.", ()),
    ],
)
def test_disclosure_replacement_preserves_only_drops_from_resolved_references(
    disclosure: str, violations: tuple[Violation, ...]
) -> None:
    affiliate = CATALOG.product("alimentacion-bebe")
    assert affiliate is not None
    active = replace(
        ACTIVE, catalog=replace(CATALOG, products=(replace(affiliate, disclosure=disclosure),))
    )
    final = finalize(
        Draft(
            "El material es digital.",
            (DraftReference("product", affiliate.id), DraftReference("product", affiliate.id)),
            ("affiliate.alimentacion-bebe.overview", "unknown"),
            ("¿Qué incluye?",),
        ),
        active,
        PriceStatus.VERIFIED,
        RULES,
        Language.EN,
    )

    assert final == FinalizedAnswer(
        "I can't confirm that with the store information I have. "
        "You can check the public product information and Hotmart help options.",
        AnswerDetails(
            links=(
                LinkRef(
                    "hotmart-purchases",
                    "Mis compras en Hotmart",
                    "https://consumer.hotmart.com/",
                ),
            ),
            notices=(Notice.ANSWER_REPLACED,),
            language="en",
        ),
        violations,
        1,
    )
