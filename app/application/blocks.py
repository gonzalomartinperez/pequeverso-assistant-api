"""Build draft v1.7 blocks from a finalized answer and the active catalog."""

from __future__ import annotations

import re
from dataclasses import asdict
from typing import TYPE_CHECKING

from app.application.answers import MAX_LINKS, product_ref
from app.domain.conversation import Notice
from app.domain.web_evidence import SOURCES

if TYPE_CHECKING:
    from app.application.answers import FinalizedAnswer
    from app.domain.catalog import ActiveCatalog, PriceStatus
    from app.domain.conversation import AnswerDetails, ImageRef, ProductRef, SourceRef

type Block = dict[str, object]

_MAX_BLOCKS = 24
_QUOTE_CHARS = 200
_MARKUP_START = re.compile(r"<(?=[A-Za-z/!])")
_HTTPS = re.compile(r"https://[^\s<>]+")


def _plain(text: str) -> bool:
    return len(text) <= 600 and "<" not in text and ">" not in text


def _https(url: str) -> bool:
    return len(url) <= 500 and _HTTPS.fullmatch(url) is not None


def _draft_image(image: ImageRef | None) -> bool:
    return image is None or (_plain(image.alt) and _https(image.url))


def _product_card(ref: ProductRef) -> Block | None:
    price = ref.price
    # The catalog permits some longer fields than the draft. Keep card facts verbatim.
    if not (
        all(
            _plain(value)
            for value in (
                ref.name,
                ref.summary,
                ref.age_range,
                ref.format or "",
                ref.disclosure or "",
            )
        )
        and _https(ref.url)
        and _https(ref.purchase_url)
        and _draft_image(ref.image)
        and (
            price is None
            or all(_plain(value) for value in (price.display, price.note, price.tax_note))
        )
    ):
        return None
    fields = asdict(ref)
    fields["product_id"] = fields.pop("id")
    if price is not None:
        fields["price"]["verified_at"] = price.verified_at.isoformat()
    return {"type": "product_card", **fields}


def _citation(source: SourceRef, active: ActiveCatalog) -> Block | None:
    if document := active.catalog.document(source.id):
        if not (_plain(document.title) and _https(document.url)):
            return None
        citation: Block = {
            "type": "citation",
            "title": document.title,
            "url": document.url,
            "source_type": "doc",
            "icon_id": "doc",
            "origin": "first_party",
        }
        quote = document.text[:_QUOTE_CHARS].rstrip()
        if quote and _plain(quote):
            citation["quote"] = quote
        return citation
    for help_source in SOURCES:
        if source.id == f"hotmart:{help_source.article_id}" and source.url == help_source.url:
            return {
                "type": "citation",
                "title": help_source.title,
                "url": help_source.url,
                "source_type": "official_help",
                "icon_id": "help",
                "origin": "web",
            }
    return None


def _notice(notice: Notice) -> Block:
    severity = (
        "warning" if notice in (Notice.ANSWER_REPLACED, Notice.PAYMENT_DATA_REFUSED) else "info"
    )
    return {"type": "notice", "code": notice.value, "severity": severity, "text_ids": ["b1"]}


def _trailing_blocks(details: AnswerDetails, active: ActiveCatalog) -> list[Block]:
    suggestions = [text for text in details.follow_ups if _plain(text)][:4]
    blocks: list[Block] = []
    if suggestions:
        blocks.append(
            {
                "type": "follow_ups",
                "items": [
                    {"id": f"f{index}", "text": text}
                    for index, text in enumerate(suggestions, start=1)
                ],
            }
        )
    chips: list[Block] = [
        {
            "type": "link_chip",
            "label": link.label,
            "url": link.url,
            "kind": "support" if link.id == active.catalog.site.support_link_id else "help",
            "icon_id": "help",
        }
        for ref in details.links
        if (link := active.catalog.link(ref.id)) and _plain(link.label) and _https(link.url)
    ]
    blocks.extend(chips[:MAX_LINKS])
    blocks.extend(_notice(notice) for notice in details.notices)
    return blocks


def _numbered(blocks: list[Block]) -> tuple[Block, ...]:
    return tuple({"id": f"b{index}", **block} for index, block in enumerate(blocks, start=1))


def build_blocks(
    answer: FinalizedAnswer,
    active: ActiveCatalog,
    price_status: PriceStatus,
    *,
    blocks_v2: bool = False,
) -> tuple[Block, ...]:
    """Return ordered JSON-ready blocks when the draft feature is enabled."""
    if not blocks_v2:
        return ()

    text: Block = {
        "type": "text",
        "markdown_lite": _MARKUP_START.sub("&lt;", answer.content),
        "claims": [],
    }
    details = answer.details
    if Notice.ANSWER_REPLACED in details.notices:
        return _numbered([text, _notice(Notice.ANSWER_REPLACED)])

    cards = [
        card
        for ref in details.products
        if (product := active.catalog.product(ref.id))
        and (card := _product_card(product_ref(active, product, price_status))) is not None
    ]
    resources: list[Block] = [
        {
            "type": "resource_card",
            "resource_id": ref.id,
            "title": ref.title,
            "pages": ref.pages,
            "image": asdict(ref.image) if ref.image is not None else None,
        }
        for ref in details.resources
        if ref.pages is not None and _plain(ref.title) and _draft_image(ref.image)
    ]
    citations = [
        citation
        for source in details.sources
        if (citation := _citation(source, active)) is not None
    ]
    trailing = _trailing_blocks(details, active)
    has_quotes = any("quote" in citation for citation in citations)
    card_limit = _MAX_BLOCKS - 1 - len(resources) - len(citations) - len(trailing) - has_quotes
    blocks: list[Block] = [text, *cards[:card_limit], *resources]
    if has_quotes:
        items = [
            {"citation_id": f"b{index}", "quote": citation["quote"]}
            for index, citation in enumerate(citations, start=len(blocks) + 1)
            if "quote" in citation
        ]
        # Finalized sources establish provenance but carry no claim-level confidence.
        trailing.insert(0, {"type": "fundamentos", "items": items, "confidence": "medium"})
    return _numbered([*blocks, *citations, *trailing])
