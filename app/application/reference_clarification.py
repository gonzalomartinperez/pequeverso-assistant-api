"""Resolve bounded immediate follow-ups without treating a topic or page as identity."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from app.domain.answer_policy import fold
from app.domain.catalog import Catalog
from app.domain.conversation import Message, Notice, Role
from app.domain.language import Language

_PRINT = re.compile(r'\b(?:imprim\w*|print\w*|descarg\w*|download\w*)\b')
_SINGULAR = re.compile(
    r'\b(?:(?:ese|este|aquel|el) producto|(?:la|esa|esta) guia|(?:this|that|the) (?:product|guide))\b'
)
_COMPARE = re.compile(r'\b(?:compar\w*|compare|comparison)\b')
_INCLUDE = re.compile(r'\b(?:incluy\w*|include\w*|trae|contains?)\b')
_MIXED = re.compile(
    r'\b(?:precio|cuesta|price|cost|stock|pedido|order|pago|payment|carrito|cart|compra|comprar|buy|agrega|add|cancel|refund|reembolso|garantia|guarantee|salud|health|alerg\w*|medical|medic\w*|password|clave|prompt|instrucciones|instructions|recomiend\w*|recommend\w*)\b'
)
_CORRECTION = re.compile(r'^(?:me refiero a|quise decir|i mean|i meant)\s+')


@dataclass(frozen=True, slots=True)
class ReferenceReply:
    product_id: str | None = None
    resource_ids: tuple[str, ...] = ()
    guide: bool = False


def clarification(language: Language, *, guide: bool = False) -> str:
    if language is Language.EN:
        return 'Which guide do you mean?' if guide else 'Which product or resource do you mean?'
    return '¿A qué guía te refieres?' if guide else '¿A qué producto o recurso te refieres?'


def _matches(text: str, values: Sequence[str]) -> bool:
    return any(re.search(r'(?<!\w)' + re.escape(fold(value)) + r'(?!\w)', text) for value in values)


def _product_ids(text: str, catalog: Catalog) -> frozenset[str]:
    named = frozenset(
        p.id for p in catalog.products if _matches(text, (p.id, p.id.replace('-', ' '), p.name))
    )
    if named:
        return named

    # A format noun can identify the subject, but a requested property cannot.
    def subject_kind(cue: str) -> bool:
        if _SINGULAR.search(text):
            return False
        bare = _CORRECTION.sub('', text).strip(' .!?¿¡')
        bare = re.sub(r'^(?:la|el|the)\s+', '', bare)
        return bool(
            re.fullmatch(cue, bare)
            or re.search(r'\b(?:el|ese|este|al|the|this|that)\s+(?:' + cue + r')\b', text)
        )

    kinds = frozenset(
        p.id
        for p in catalog.products
        for cue in (r'(?:curso|course)s?', r'videos?', r'pdfs?')
        if subject_kind(cue) and re.search(r'\b(?:' + cue + r')\b', fold(p.format))
    )
    if subject_kind('kit'):
        kinds |= frozenset(
            p.id for p in catalog.products if re.search(r'\bkit\b', fold(p.format + ' ' + p.summary))
        )
    if len(kinds) == 1:
        return kinds
    # A canonical name prefix is explicit only when it contains at least two meaningful words.
    prefixes = {p.id: ' '.join(fold(p.name).split()[:3]) for p in catalog.products}
    return frozenset(
        p.id
        for p in catalog.products
        if _matches(text, (prefixes[p.id],)) and list(prefixes.values()).count(prefixes[p.id]) == 1
    )


def _bare_correction_ids(text: str, catalog: Catalog) -> frozenset[str]:
    bare = _CORRECTION.sub('', text).strip(' .!?¿¡')
    bare = re.sub(r'^(?:la|el|the)\s+', '', bare)
    named = frozenset(
        p.id
        for p in catalog.products
        if bare in {fold(p.id), fold(p.id.replace('-', ' ')), fold(p.name)}
        or (len(bare.split()) >= 2 and fold(p.name).startswith(bare + ' '))
    )
    if named:
        return named
    if bare in {'curso', 'course', 'video', 'pdf', 'kit'}:
        return _product_ids(bare, catalog)
    return frozenset()


def _plain(answer: Message) -> bool:
    d = answer.details
    return not (d.products or d.resources or d.links or d.sources or d.follow_ups or d.notices)


def _previous(history: Sequence[Message], catalog: Catalog) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if len(history) < 2 or history[-2].role is not Role.USER or history[-1].role is not Role.ASSISTANT:
        return (), ()
    d = history[-1].details
    if any(
        n in d.notices
        for n in (Notice.ANSWER_REPLACED, Notice.PAYMENT_DATA_REFUSED, Notice.LANGUAGE_UNSUPPORTED)
    ):
        return (), ()
    if any((doc := catalog.document(s.id)) is None or doc.url != s.url for s in d.sources):
        return (), ()
    products = tuple(p.id for p in d.products)
    resources = tuple(r.id for r in d.resources)
    if any(catalog.product(p) is None for p in products) or any(
        catalog.resource(r) is None for r in resources
    ):
        return (), ()
    if len(set(products)) != len(products) or len(set(resources)) != len(resources):
        return (), ()
    return products, resources


def reference_reply(question: str, catalog: Catalog, history: Sequence[Message]) -> ReferenceReply | None:
    """None keeps ordinary flow. Plans carry only active canonical identities, never new facts."""
    text = fold(question)
    if not text or len(text) > 320 or '\n' in text or _MIXED.search(text):
        return None
    explicit_products = _product_ids(text, catalog)
    explicit_resources = tuple(
        p.id + '/' + r.id
        for p in catalog.products
        for r in p.resources
        if _matches(text, (r.title, p.id + '/' + r.id))
    )
    if len(history) >= 2 and history[-2].role is Role.USER and history[-1].role is Role.ASSISTANT:
        answer = history[-1]
        local_clarification = _plain(answer) and answer.content in {clarification(lang) for lang in Language}
        if (
            local_clarification
            and _PRINT.search(fold(history[-2].content))
            and len(explicit_products) == 1
            and not explicit_resources
            and _bare_correction_ids(text, catalog) == explicit_products
        ):
            return ReferenceReply(product_id=next(iter(explicit_products)))
    products, resources = _previous(history, catalog)
    if len(products) < 2 and len(resources) < 2:
        return None
    if explicit_products or explicit_resources:
        return None
    if (
        len(resources) >= 2
        and _COMPARE.search(text)
        and _INCLUDE.search(text)
        and re.search(r'\b(?:guia|guide)\b', text)
    ):
        return ReferenceReply(resource_ids=resources, guide=True)
    if re.search(r'\b(?:ambos|ambas|los dos|las dos|both|they|these products|those products)\b', text):
        return None
    if _SINGULAR.search(text) or _PRINT.search(text):
        # Other mixed asks remain model-grounded; this shortcut only asks for a referent.
        return ReferenceReply()
    return None
