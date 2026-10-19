"""Bounded price-comparison intent and current-catalog referents, without page defaults.

This is not a general semantic classifier. Mixed requests keep the ordinary assistant flow;
clear comparisons with unresolved referents ask for clarification rather than guessing.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from app.domain.answer_policy import fold
from app.domain.catalog import Catalog, Product, mentioned_products
from app.domain.conversation import Message, Notice, Role
from app.domain.language import Language

_PRICE = re.compile(
    r'\b(?:precio|precios|cuesta|cuestan|coste|costo|costos|vale|valen|valor|price|prices|cost|costs|priced)\b'
)
_RELATION = re.compile(
    r'\b(?:mismo|misma|mismos|mismas|igual|iguales|diferente|diferentes|distinto|distintos|same|equal|different)\b'
)
_COMPARATIVE = re.compile(
    r'\b(?:mas|menos)\s+(?:barat[oa]s?|car[oa]s?|costos[oa]s?)\b|\b(?:cheaper|cheapest|pricier|more expensive|less expensive)\b'
)
_GROUP = re.compile(r'\b(?:ambos|ambas|los dos|las dos|estos dos|estas dos|both|the two|two products)\b')
_OTHER = re.compile(r'\b(?:el otro|la otra|the other)\b')
_MIXED = re.compile(
    r'\b(?:stock|disponibilidad|availability|garantia|guarantee|refund|reembolso|devolucion|'
    r'pedido|pedidos|orders?|carrito|cart|checkout|agrega|add|cancelar|cancel|'
    r'descuentos?|discounts?|cupones?|coupons?|soporte|support|'
    r'recomiend[ao]s?|recomendar|recomendacion|recommend|recommends|recommendation|recommended|'
    r'choose|choosing|choice|elegir|elijo|elija|escojo|escoger|conviene|'
    r'entrega|delivery|acceso|access|descarga|download|formato|format|contenido|content|'
    r'edad|edades|ages?|salud|health|medical|medic[oa]|anemia|alergias?|allergy|allergies|'
    r'curar|cura|cures?|treat|treatment|diagnostico|diagnosis|dosis|dose|contrasena|password|secreto|secret|'
    r'credenciales|credentials|prompt|instructions|instrucciones|sql|api)\b'
)
_RESOURCE = re.compile(r'\b(?:bonos?|bonuses|resources?|recursos?|pdfs?|paginas|pages)\b')
_NO_COMPARE = re.compile(
    r"\b(?:no compares|no comparar|no quiero comparar|do not compare|don't compare|dont compare)\b"
)


def clarification(language: Language) -> str:
    return (
        'Which products would you like to compare in price?'
        if language is Language.EN
        else '¿Qué productos quieres comparar en precio?'
    )


def _price_intent(text: str) -> bool:
    price = bool(_PRICE.search(text))
    return bool(
        _COMPARATIVE.search(text)
        or (price and (_RELATION.search(text) or _GROUP.search(text)))
        or (price and re.search(r'\b(?:mas|menos|more|less)\b', text))
    )


def _history_pair(history: Sequence[Message], catalog: Catalog) -> frozenset[str]:
    if len(history) < 2 or history[-1].role is not Role.ASSISTANT or history[-2].role is not Role.USER:
        return frozenset()
    answer = history[-1]
    if any(
        notice in answer.details.notices
        for notice in (Notice.ANSWER_REPLACED, Notice.PAYMENT_DATA_REFUSED, Notice.LANGUAGE_UNSUPPORTED)
    ):
        return frozenset()
    if any(
        (document := catalog.document(source.id)) is None or document.url != source.url
        for source in answer.details.sources
    ):
        return frozenset()
    ids = frozenset(p.id for p in answer.details.products if catalog.product(p.id) is not None)
    previous = mentioned_products(history[-2].content, catalog)
    if len(ids) >= 2 and len(ids) == len(answer.details.products) and (not previous or previous == ids):
        return ids
    return frozenset()


def comparison_products(
    question: str, catalog: Catalog, history: Sequence[Message]
) -> tuple[Product, ...] | None:
    """None retains ordinary flow; empty tuple requests a short referent clarification."""
    text = fold(question)
    if not text or len(text) > 320 or '\n' in text or _MIXED.search(text) or _NO_COMPARE.search(text):
        return None
    named = frozenset(
        product.id
        for product in catalog.products
        if any(
            re.search(r'(?<!\w)' + re.escape(fold(value)) + r'(?!\w)', text)
            for value in (product.id, product.id.replace('-', ' '), product.name)
        )
    )
    current = named if len(named) >= 2 else mentioned_products(text, catalog)
    previous_price = (
        len(history) >= 2
        and history[-2].role is Role.USER
        and history[-1].role is Role.ASSISTANT
        and _price_intent(fold(history[-2].content))
    )
    clarify_followup = (
        previous_price
        and history[-1].content in (clarification(Language.ES), clarification(Language.EN))
        and not (
            history[-1].details.products
            or history[-1].details.resources
            or history[-1].details.links
            or history[-1].details.sources
            or history[-1].details.follow_ups
            or history[-1].details.notices
        )
        and len(current) >= 2
    )
    if not (_price_intent(text) or (previous_price and _RELATION.search(text)) or clarify_followup):
        return None
    # A pair of bonuses/PDFs is not a pair of catalog products. Preserve that existing flow.
    if _RESOURCE.search(text) and len(current) < 2:
        return None
    prior = _history_pair(history, catalog)
    if len(current) == 1 and not (
        _GROUP.search(text) or _OTHER.search(text) or prior or _COMPARATIVE.search(text)
    ):
        # Reconfirming one known product's price is not a comparison between products.
        return None
    selected = current if len(current) >= 2 else frozenset()
    if (
        not selected
        and (_GROUP.search(text) or (current and _OTHER.search(text)))
        and len(catalog.products) == 2
        and (not history or len(prior) >= 2)
    ):
        selected = frozenset(p.id for p in catalog.products)
    if not selected and (not current or current.issubset(prior)):
        selected = prior
    return tuple(p for p in catalog.products if p.id in selected)
