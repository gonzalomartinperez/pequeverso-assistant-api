"""Bounded explicit numeric page claims, not general semantic entailment.

Only named catalog resources/products and short shared references are resolved. Printing
subsets are not total-page assertions. Unknown subjects remain outside this recognizer.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from app.domain.catalog import Catalog
from app.domain.web_evidence import negated_at


@dataclass(frozen=True)
class _Entity:
    key: str
    pages: int
    product: bool
    aliases: tuple[str, ...]


def _normalize(text: str) -> str:
    return ''.join(
        c for c in unicodedata.normalize('NFD', text.casefold()) if not unicodedata.combining(c)
    ).replace('-', ' ')


def _entities(catalog: Catalog) -> tuple[_Entity, ...]:
    items: list[_Entity] = []
    for product in catalog.products:
        for resource in product.resources:
            if resource.pages is not None:
                items.append(
                    _Entity(
                        f'{product.id}/{resource.id}',
                        resource.pages,
                        False,
                        (
                            _normalize(resource.title),
                            _normalize(f'{product.id}/{resource.id}'),
                            *((_normalize(resource.id),) if resource.id.isalpha() else ()),
                        ),
                    )
                )
        aliases = (_normalize(product.name), _normalize(product.id))
        if len(catalog.products) == 1:
            aliases += ('kit',)
        items.append(_Entity(product.id, product.page_count, True, aliases))
    return tuple(items)


_PAGES = re.compile(r'\b(\d{1,5})\s+(?:paginas?|pages?)\b')
_SHARED = re.compile(r'\b(?:ambos|ambas|both|cada uno|cada una|each)\b')
_TOTAL = re.compile(r'\b(?:en total|suman|suma|juntos|juntas|combined|altogether|together|in total)\b')
_SUBSET = re.compile(
    r'\b(?:imprimir|imprime|imprimes|imprimiendo|imprimas|print|printing|choose|select|elige|elegir|escoge|selecciona)\b'
)


def unsupported_page_claim(text: str, catalog: Catalog) -> bool:
    """Reject a recognized assertion inconsistent with active structured page metadata."""
    normalized = _normalize(text)
    entities = _entities(catalog)
    previous: list[_Entity] = []
    for sentence in re.split(r'[.!?;\n]', normalized):
        mentions: list[tuple[int, int, _Entity]] = []
        for entity in entities:
            aliases = '|'.join(re.escape(a) for a in sorted(set(entity.aliases), key=len, reverse=True))
            mentions.extend(
                (m.start(), m.end(), entity) for m in re.finditer(rf'(?<!\w)(?:{aliases})(?!\w)', sentence)
            )
        # A product title embedded in a resource title is not a second subject.
        mentions = [
            m
            for m in mentions
            if not (
                m[2].product and any(not r[2].product and r[0] <= m[0] and r[1] >= m[1] for r in mentions)
            )
        ]
        mentions.sort(key=lambda m: (m[0], m[1]))
        for claim in _PAGES.finditer(sentence):
            if negated_at(sentence, claim.start()):
                continue
            # Explicit print/selection quantities are subsets, not the PDF's size.
            clause_start = (
                max(sentence.rfind(',', 0, claim.start()), sentence.rfind(':', 0, claim.start())) + 1
            )
            clause = sentence[clause_start : claim.start()]
            if _SUBSET.search(clause):
                continue
            before = [m for m in mentions if m[0] < claim.start()]
            resources = [m[2] for m in before if not m[2].product]
            local_resources = list(dict.fromkeys(resources))
            after = [m for m in mentions if m[0] >= claim.end()]
            scope_start = before[-1][1] if before else clause_start
            scope_end = after[0][0] if after else len(sentence)
            scope = sentence[scope_start:scope_end]
            shared = _SHARED.search(scope) is not None
            total = _TOTAL.search(scope) is not None
            value = int(claim.group(1))
            if shared:
                subjects = local_resources or previous[-2:]
                if subjects and any(subject.pages != value for subject in subjects):
                    return True
            elif total and local_resources and not any(m[2].product for m in before):
                if sum(resource.pages for resource in local_resources) != value:
                    return True
            elif before:
                subject = before[-1][2]
                if total:
                    subject = next((m[2] for m in reversed(before) if m[2].product), subject)
                if subject.pages != value:
                    return True
            else:
                # "40 pages in Safari" is an explicit local resource attribution.
                after = [m for m in mentions if m[0] >= claim.end()]
                if (
                    after
                    and re.fullmatch(
                        r'\s*(?:de|del|en|in|of|for|from)\s+', sentence[claim.end() : after[0][0]]
                    )
                    and after[0][2].pages != value
                ):
                    return True
        for _, _, entity in mentions:
            if not entity.product:
                previous = [old for old in previous if old.key != entity.key]
                previous.append(entity)
    return False
