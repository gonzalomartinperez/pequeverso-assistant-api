"""Draft blocks keep the finalized answer and the catalog's public facts in order."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.application.answers import FinalizedAnswer, answer_rules, finalize
from app.application.blocks import Block, build_blocks
from app.application.ports import Draft, DraftReference
from app.domain.catalog import ActiveCatalog, PriceStatus
from app.domain.conversation import Notice
from evals import graders
from tests.test_draft_contract_schemas import _validator
from tests.test_eval_graders import item, message

CATALOG = graders.CATALOG
ACTIVE = ActiveCatalog(CATALOG, "sha", CATALOG.generated_at, timedelta(hours=168))
PRODUCT_ID = "grafismo-fonetico"
RESOURCE_ID = "grafismo-fonetico/juega"
VALIDATOR = _validator("blocks")


def _finalize(draft: Draft, status: PriceStatus = PriceStatus.VERIFIED) -> FinalizedAnswer:
    return finalize(draft, ACTIVE, status, answer_rules(CATALOG, status, ()))


def _assert_blocks(
    blocks: tuple[Block, ...],
    expected: list[str],
    status: PriceStatus = PriceStatus.VERIFIED,
) -> None:
    wire = json.loads(json.dumps({"blocks": blocks}))
    VALIDATOR.validate(wire)
    assert [b["type"] for b in blocks] == expected
    ctx = graders.GradeContext(
        item=item(expected_blocks=expected),
        final=message("x"),
        stale=status is PriceStatus.UNVERIFIED,
        extra=wire,
    )
    assert graders.blocks_price(ctx) == []
    assert graders.blocks_closed_union(ctx) == []
    assert graders.blocks_expected(ctx) == []


def test_recommendation_looks_up_product_fields_and_drops_unknown_id() -> None:
    final = _finalize(
        Draft(
            "Te recomiendo el kit.",
            (DraftReference("product", PRODUCT_ID), DraftReference("product", "inventado")),
            (),
            (),
        )
    )
    assert final.dropped_references == 1
    (ref,) = final.details.products
    # Even an already-built reference can be from another snapshot. Use only its ID.
    forged = replace(ref, name="Inventado", summary="Inventado", url="https://example.com")
    final = replace(
        final, details=replace(final.details, products=(forged, replace(ref, id="inventado")))
    )

    blocks = build_blocks(final, ACTIVE, PriceStatus.VERIFIED, blocks_v2=True)
    _assert_blocks(blocks, ["text", "product_card"])
    text, card = blocks
    assert text["markdown_lite"] == final.content
    assert text["claims"] == []
    assert card["product_id"] == PRODUCT_ID
    assert card["name"] == ref.name
    assert card["summary"] == ref.summary
    assert card["age_range"] == ref.age_range
    assert card["url"] == ref.url
    assert card["purchase_url"] == ref.purchase_url
    assert card["kind"] == ref.kind
    assert card["format"] == ref.format
    assert card["disclosure"] == ref.disclosure
    assert ref.image is not None
    assert card["image"] == {
        "url": ref.image.url,
        "width": ref.image.width,
        "height": ref.image.height,
        "alt": ref.image.alt,
    }


def test_blocks_are_off_by_default() -> None:
    final = _finalize(Draft("Te recomiendo el kit.", (), (), ()))
    assert build_blocks(final, ACTIVE, PriceStatus.VERIFIED) == ()


def test_replaced_answer_has_no_cards_but_keeps_its_support_route() -> None:
    final = _finalize(
        Draft("Cuesta US$5.", (DraftReference("product", PRODUCT_ID),), (), ("¿Qué incluye?",))
    )
    assert final.details.notices == (Notice.ANSWER_REPLACED,)
    assert final.details.links  # The v1 replacement includes a support link.
    blocks = build_blocks(final, ACTIVE, PriceStatus.VERIFIED, blocks_v2=True)

    _assert_blocks(blocks, ["text", "link_chip", "notice"])
    assert blocks[0]["markdown_lite"] == final.content
    assert blocks[1]["kind"] == "support"
    assert blocks[2] == {
        "id": "b3",
        "type": "notice",
        "code": "answer_replaced",
        "severity": "warning",
        "text_ids": ["b1"],
    }


@pytest.mark.parametrize("finalization_status", list(PriceStatus))
def test_unverified_price_is_null_even_with_an_old_verified_reference(
    finalization_status: PriceStatus,
) -> None:
    final = _finalize(
        Draft(
            "Puedes revisar el precio actual en la página del kit.",
            (DraftReference("product", PRODUCT_ID),),
            (),
            (),
        ),
        finalization_status,
    )
    stale = ACTIVE.price_status(ACTIVE.verified_at + ACTIVE.max_price_age + timedelta(seconds=1))
    blocks = build_blocks(final, ACTIVE, stale, blocks_v2=True)

    _assert_blocks(blocks, ["text", "product_card"], PriceStatus.UNVERIFIED)
    assert blocks[1]["price"] is None


def test_resource_link_sources_and_follow_ups_use_draft_shapes_and_order() -> None:
    final = _finalize(
        Draft(
            "También puedes revisar este recurso del kit.",
            (DraftReference("resource", RESOURCE_ID), DraftReference("link", "support")),
            ("faq.grafismo-fonetico.05",),
            ("¿Qué incluye el kit?", "¿Cuántos PDF trae?"),
        )
    )
    blocks = build_blocks(final, ACTIVE, PriceStatus.VERIFIED, blocks_v2=True)

    _assert_blocks(blocks, ["text", "resource_card", "citation", "follow_ups", "link_chip"])
    _, resource, citation, follow_ups, link = blocks
    (ref,) = final.details.resources
    (source,) = final.details.sources
    (support,) = final.details.links
    document = CATALOG.document(source.id)
    assert document is not None
    assert resource["resource_id"] == RESOURCE_ID
    assert resource["title"] == ref.title
    assert resource["pages"] == ref.pages
    assert citation["title"] == source.title
    assert citation["url"] == source.url
    quote = citation["quote"]
    assert isinstance(quote, str) and 0 < len(quote) <= 200 and quote in document.text
    assert follow_ups["items"] == [
        {"id": "f1", "text": "¿Qué incluye el kit?"},
        {"id": "f2", "text": "¿Cuántos PDF trae?"},
    ]
    assert link["kind"] == "support"
    assert (link["label"], link["url"]) == (support.label, support.url)


@given(
    ids=st.lists(
        st.sampled_from(tuple(p.id for p in CATALOG.products)),
        min_size=1,
        unique=True,
    ),
    status=st.sampled_from(list(PriceStatus)),
    cents=st.integers(min_value=1, max_value=999_999),
)
def test_every_card_price_is_from_the_active_snapshot(ids, status, cents) -> None:
    final = _finalize(
        Draft(
            "Puedes consultar estos productos.",
            tuple(DraftReference("product", i) for i in ids),
            (),
            (),
        )
    )
    products = tuple(
        replace(p, price=replace(p.price, amount=Decimal(cents).scaleb(-2)))
        if p.price is not None
        else p
        for p in CATALOG.products
    )
    active = replace(ACTIVE, catalog=replace(CATALOG, products=products))
    blocks = build_blocks(final, active, status, blocks_v2=True)
    VALIDATOR.validate(json.loads(json.dumps({"blocks": blocks})))
    cards = [b for b in blocks if b["type"] == "product_card"]
    assert [card["product_id"] for card in cards] == ids
    for card, sku in zip(cards, ids, strict=True):
        product = active.catalog.product(sku)
        assert product is not None
        price = product.price
        if price is None or status is PriceStatus.UNVERIFIED:
            assert card["price"] is None
        else:
            assert card["price"] == {
                "amount": f"{price.amount:.2f}",
                "currency": price.currency,
                "display": price.display,
                "note": price.note,
                "tax_note": price.tax_note,
                "verified_at": active.verified_at.isoformat(),
            }


def test_resource_cards_come_from_the_catalog_not_the_finalized_ref() -> None:
    final = _finalize(
        Draft("Te cuento sobre el recurso.", (DraftReference("resource", RESOURCE_ID),), (), ())
    )
    (ref,) = final.details.resources
    forged = replace(
        final, details=replace(final.details, resources=(replace(ref, title="FORGED", pages=999),))
    )
    blocks = build_blocks(forged, ACTIVE, PriceStatus.VERIFIED, blocks_v2=True)
    (card,) = [b for b in blocks if b["type"] == "resource_card"]
    assert (card["title"], card["pages"]) == (ref.title, ref.pages)


def test_a_price_withheld_at_finalization_stays_withheld_in_the_card() -> None:
    final = _finalize(
        Draft("Mira el kit.", (DraftReference("product", PRODUCT_ID),), (), ()),
        PriceStatus.UNVERIFIED,
    )
    (ref,) = final.details.products
    assert ref.price is None
    blocks = build_blocks(final, ACTIVE, PriceStatus.VERIFIED, blocks_v2=True)
    (card,) = [b for b in blocks if b["type"] == "product_card"]
    assert card["price"] is None


def test_duplicate_product_refs_give_one_card_and_markup_becomes_a_lookalike() -> None:
    final = _finalize(Draft("Hola <b y <?x", (DraftReference("product", PRODUCT_ID),), (), ()))
    doubled = replace(final, details=replace(final.details, products=final.details.products * 2))
    blocks = build_blocks(doubled, ACTIVE, PriceStatus.VERIFIED, blocks_v2=True)
    assert [b["type"] for b in blocks].count("product_card") == 1
    assert "<" not in str(blocks[0]["markdown_lite"])
