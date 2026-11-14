"""Block graders and v2 item-schema extensions (PVA-M2-X): every branch exercised."""

from __future__ import annotations

import copy
from typing import Any

import pytest

from evals import graders, schema
from evals.graders import ALWAYS, GradeContext
from tests.test_eval_graders import item, message

PRICE = {
    "amount": "14.99",
    "currency": "USD",
    "display": "US$14,99",
    "note": "n",
    "tax_note": "t",
    "verified_at": "2026-11-10T12:00:00Z",
}


def card(**changes: Any) -> dict[str, Any]:
    base = {"id": "b1", "type": "product_card", "product_id": "grafismo-fonetico", "price": PRICE}
    return base | changes


def run(name: str, blocks: list[dict[str, Any]], *, stale: bool = False, **it: Any) -> list[str]:
    ctx = GradeContext(item=item(**it), final=message("x"), stale=stale, extra={"blocks": blocks})
    return graders.GRADERS[name](ctx)


def test_new_graders_are_registered_but_not_always() -> None:
    for name in ("blocks.price", "blocks.closed_union", "blocks.expected"):
        assert name in graders.GRADERS
        assert name not in ALWAYS
    assert "guarantee.days" in graders.GRADERS  # pre-existing, not duplicated


def test_no_blocks_is_clean() -> None:
    ctx = GradeContext(item=item(), final=message("x"))
    assert all(graders.GRADERS[n](ctx) == [] for n in ("blocks.price", "blocks.closed_union"))


@pytest.mark.parametrize(
    ("blocks", "stale", "expected"),
    [
        ([card()], False, []),
        ([{"id": "b1", "type": "text"}], False, []),
        ([card(price=None)], False, []),
        ([card(price=None)], True, []),
        ([card(product_id="ghost")], False, ["not a catalog product"]),
        ([card()], True, ["while unverified"]),
        ([card(price=PRICE | {"amount": "1.00"})], False, ["differs from the catalog"]),
        ([card(price=PRICE | {"display": "US$1"})], False, ["differs from the catalog"]),
    ],
)
def test_blocks_price(blocks: list[dict[str, Any]], stale: bool, expected: list[str]) -> None:
    problems = run("blocks.price", blocks, stale=stale)
    assert len(problems) == len(expected)
    assert all(want in got for want, got in zip(expected, problems, strict=True))


def test_blocks_price_when_catalog_has_no_price(monkeypatch: pytest.MonkeyPatch) -> None:
    product = copy.copy(graders.CATALOG.products[0])
    object.__setattr__(product, "price", None)
    monkeypatch.setattr(graders, "CATALOG", type("C", (), {"products": (product,)})())
    problems = run("blocks.price", [card(product_id=product.id)])
    assert problems == [f"product card {product.id} price differs from the catalog"]


@pytest.mark.parametrize(
    ("blocks", "expected"),
    [
        ([{"id": "b1", "type": "text"}, {"id": "b2", "type": "citation"}], []),
        ([{"id": "b1", "type": "carousel"}], ["unknown block type 'carousel'"]),
        ([{"id": "b1", "type": "text"}, {"id": "b1", "type": "notice"}], ["duplicate block id"]),
        ([{"id": "b1", "type": "notice"}, {"id": "b2", "type": "text"}], ["out of order"]),
        ([{"id": "b1", "type": "text", "markdown_lite": "<b>x</b>"}], ["carries markup"]),
        ([{"id": "b1", "type": "text", "markdown_lite": "2 < 3 y 5 > 4"}], []),
    ],
)
def test_blocks_closed_union(blocks: list[dict[str, Any]], expected: list[str]) -> None:
    problems = run("blocks.closed_union", blocks)
    assert len(problems) == len(expected)
    assert all(want in got for want, got in zip(expected, problems, strict=True))


def test_blocks_expected() -> None:
    blocks = [{"type": "text"}, {"type": "product_card"}, {"type": "notice"}]
    assert run("blocks.expected", blocks, expected_blocks=["text", "notice"]) == []
    assert run("blocks.expected", blocks) == []
    assert run("blocks.expected", blocks, expected_blocks=["notice", "text"]) == [
        "expected block text missing"
    ]


# --- item-schema extensions ------------------------------------------------------------------------

ITEMS = schema.load()


def _with(**changes: Any) -> list[dict[str, Any]]:
    items = copy.deepcopy(ITEMS)
    items[0].update(changes)
    return items


def test_golden_stays_valid_and_v2_keys_are_optional() -> None:
    assert schema.validate(ITEMS) == []
    assert all(not (schema.V2_OPTIONAL & set(i)) for i in ITEMS)


def test_valid_v2_keys_are_accepted() -> None:
    items = _with(
        expected_blocks=["text", "product_card"],
        expected_progress=["understanding", "writing"],
        memory_fixture={"verbosity": "short"},
        consent=True,
    )
    assert schema.validate(items, counts=False) == []


@pytest.mark.parametrize(
    ("changes", "message_"),
    [
        ({"expected_blocks": ["carousel"]}, "expected_blocks must be a list of known values"),
        ({"expected_blocks": [["text"]]}, "expected_blocks must be a list"),
        ({"expected_blocks": "text"}, "expected_blocks must be a list"),
        ({"expected_progress": ["retrieving"]}, "expected_progress must be a list"),
        ({"memory_fixture": {"child_name": "x"}}, "closed memory schema"),
        ({"memory_fixture": ["x"], "consent": True}, "closed memory schema"),
        ({"consent": "yes"}, "consent must be a boolean"),
        ({"memory_fixture": {"verbosity": "short"}}, "needs consent true"),
        ({"memory_fixture": {"verbosity": "short"}, "consent": False}, "needs consent true"),
    ],
)
def test_invalid_v2_keys_are_reported(changes: dict[str, Any], message_: str) -> None:
    problems = schema.validate(_with(**changes), counts=False)
    assert any(message_ in p for p in problems), problems
