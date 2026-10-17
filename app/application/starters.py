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
    affiliates = [p for p in catalog.products if p.kind == 'affiliate']
    core = next((p for p in catalog.products if p.kind == 'core'), None)
    if affiliates and core is not None:
        affiliate = affiliates[0]
        if language is Language.ES:
            return (
                f'¿Qué incluye {core.name}?',
                f'¿Para qué edades es {core.name}?',
                f'¿Qué enseña {"la " if affiliate.name.startswith("Guía ") else ""}{affiliate.name}?',
                f'¿Qué diferencias hay entre {core.name} y {affiliate.name}?',
            )
        return (
            f'What does {core.name} include?',
            f'Which ages is {core.name} for?',
            f'What does {affiliate.name} cover?',
            f'How do {core.name} and {affiliate.name} differ?',
        )
    return tuple(chosen)
