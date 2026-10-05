"""Opening questions shown before the first message, built only from approved catalog topics.

Spanish starters reuse the storefront's own FAQ questions. English starters are fixed
translations of the same topics, offered only when the topic exists in the active catalog, so
a starter never asks about something the catalog cannot answer.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.answer_policy import fold
from app.domain.catalog import Catalog, DocumentKind
from app.domain.language import Language

MAX_STARTERS = 4


@dataclass(frozen=True, slots=True)
class _Topic:
    keywords: tuple[str, ...]
    english: str


_TOPICS = (
    _Topic(('incluye',), 'What does {product} include?'),
    _Topic(('edades', 'edad'), 'Which ages is {product} for?'),
    _Topic(('imprimir',), 'Do I need to print all the material?'),
    _Topic(('garantia',), 'How does the guarantee work?'),
    _Topic(('saber leer',), 'Does my child need to know how to read already?'),
)


def starters(catalog: Catalog, language: Language) -> tuple[str, ...]:
    if not catalog.products:
        return ()
    product = catalog.products[0].name
    faqs = [d for d in catalog.documents if d.kind is DocumentKind.FAQ and d.title.endswith('?')]
    chosen: list[str] = []
    for topic in _TOPICS:
        match = next((d for d in faqs if any(k in fold(d.title) for k in topic.keywords)), None)
        if match is None:
            continue
        chosen.append(topic.english.format(product=product) if language is Language.EN else match.title)
        if len(chosen) == MAX_STARTERS:
            break
    return tuple(chosen)
