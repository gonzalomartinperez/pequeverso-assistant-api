"""Grounding evidence built from the active catalog.

The catalog is small (one kit, its resources, FAQ and policies), so the whole compact catalog is
sent while it fits `max_chars`, in stable order so the provider can cache the prefix. Lexical
ranking decides which documents stay when it does not fit, and orders documents for the
retrieval evaluation (evals/retrieval.json). Embeddings are deliberately absent: see
docs/decisions/ADR-0002-grounding-without-embeddings.md.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from app.domain.answer_policy import fold
from app.domain.catalog import Catalog, Document, PriceStatus, Product, resource_key

_WORD = re.compile(r'[a-z0-9ñ]+')
_STOPWORDS = frozenset(
    [
        'a',
        'al',
        'algo',
        'como',
        'con',
        'cual',
        'cuales',
        'de',
        'del',
        'el',
        'ella',
        'en',
        'es',
        'esa',
        'ese',
        'eso',
        'esta',
        'este',
        'esto',
        'hay',
        'la',
        'las',
        'lo',
        'los',
        'me',
        'mi',
        'mis',
        'muy',
        'no',
        'o',
        'para',
        'pero',
        'por',
        'que',
        'quiero',
        'se',
        'si',
        'sin',
        'son',
        'su',
        'sus',
        'te',
        'tengo',
        'tiene',
        'tu',
        'un',
        'una',
        'uno',
        'unos',
        'y',
        'ya',
        'yo',
        'puedo',
        'puede',
        'hola',
        'gracias',
        'cuanto',
        'cuanta',
    ]
)


def tokens(text: str) -> list[str]:
    words = _WORD.findall(fold(text))
    return [_stem(word) for word in words if word not in _STOPWORDS and len(word) > 1]


def _stem(word: str) -> str:
    """Tiny Spanish plural folding: 'silabas' → 'silaba', 'sonidos' → 'sonido'."""
    for suffix in ('es', 's'):
        if len(word) > 4 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


@dataclass(frozen=True, slots=True)
class Passage:
    """A rankable unit: a document, a resource or the product overview."""

    id: str
    text: str


def passages(catalog: Catalog) -> list[Passage]:
    items: list[Passage] = []
    for product in catalog.products:
        overview = ' '.join(
            [
                product.name,
                product.summary,
                product.format,
                product.usage,
                product.age_range,
                *product.method,
                *product.audience_for,
                *product.audience_not_for,
                *(f'{g.label} {g.hint}' for g in product.age_guidance),
            ]
        )
        items.append(Passage(f'product:{product.id}', overview))
        items.extend(
            Passage(f'resource:{resource_key(product.id, r.id)}', f'{r.title} {r.description}')
            for r in product.resources
        )
    items.extend(Passage(f'document:{d.id}', f'{d.title} {d.text}') for d in catalog.documents)
    return items


def rank(query: str, items: Sequence[Passage]) -> list[tuple[Passage, float]]:
    """BM25-style lexical scores, highest first; ties keep catalog order."""
    query_terms = tokens(query)
    docs = [tokens(item.text) for item in items]
    if not query_terms or not items:
        return [(item, 0.0) for item in items]
    avg_len = sum(len(d) for d in docs) / len(docs) or 1.0
    frequency = Counter(term for d in docs for term in set(d))
    scored: list[tuple[Passage, float]] = []
    for item, doc in zip(items, docs, strict=True):
        counts = Counter(doc)
        score = 0.0
        for term in set(query_terms):
            tf = counts.get(term, 0)
            if not tf:
                continue
            idf = math.log(1 + (len(docs) - frequency[term] + 0.5) / (frequency[term] + 0.5))
            score += idf * tf * 2.2 / (tf + 1.2 * (0.25 + 0.75 * len(doc) / avg_len))
        scored.append((item, score))
    return sorted(scored, key=lambda pair: -pair[1])


def _product_payload(product: Product, price_status: PriceStatus) -> dict[str, Any]:
    payload: dict[str, Any] = {
        'id': product.id,
        'name': product.name,
        'summary': product.summary,
        'age_range': product.age_range,
        'format': product.format,
        'usage': product.usage,
        'pdf_count': product.pdf_count,
        'page_count': product.page_count,
        'method': list(product.method),
        'good_fit_when': list(product.audience_for),
        'not_a_fit_when': list(product.audience_not_for),
        'age_guidance': [{'age': g.label, 'where_to_start': g.hint} for g in product.age_guidance],
        'resources': [
            {
                'id': resource_key(product.id, r.id),
                'title': r.title,
                'pages': r.pages,
                'description': r.description,
            }
            for r in product.resources
        ],
    }
    if price_status is PriceStatus.VERIFIED:
        payload['price'] = {
            'display': product.price.display,
            'currency': product.price.currency,
            'currency_note': product.price.note,
            'tax_note': product.price.tax_note,
        }
    return payload


def _documents_payload(documents: Iterable[Document]) -> list[dict[str, str]]:
    return [{'id': d.id, 'kind': d.kind.value, 'title': d.title, 'text': d.text} for d in documents]


def catalog_payload(catalog: Catalog, price_status: PriceStatus, query: str, max_chars: int) -> str:
    """Compact JSON evidence; drops the lowest-ranked documents only when over `max_chars`."""
    base: dict[str, Any] = {
        'store': {
            'name': catalog.site.name,
            'language': catalog.site.language,
            'support_email': catalog.site.support_email,
        },
        'price_status': price_status.value,
        'products': [_product_payload(p, price_status) for p in catalog.products],
        'links': [{'id': link.id, 'label': link.label} for link in catalog.links],
        'documents': _documents_payload(catalog.documents),
    }
    text = json.dumps(base, ensure_ascii=False, separators=(',', ':'))
    if len(text) <= max_chars:
        return text
    ranked = [
        p.id.removeprefix('document:')
        for p, _ in rank(query, passages(catalog))
        if p.id.startswith('document:')
    ]
    kept: list[Document] = []
    for document_id in ranked:
        document = catalog.document(document_id)
        if document is None:
            continue
        candidate = {**base, 'documents': _documents_payload([*kept, document])}
        if len(json.dumps(candidate, ensure_ascii=False, separators=(',', ':'))) > max_chars:
            break
        kept.append(document)
    base['documents'] = _documents_payload(kept)
    return json.dumps(base, ensure_ascii=False, separators=(',', ':'))
