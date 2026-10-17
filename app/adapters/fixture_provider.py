"""Deterministic stand-in for the model (development, CI, contract fixtures).

It reads the same `store_data` and `visitor_turn` payloads a real model receives and builds a
schema-valid answer from the best lexical matches, streamed in small chunks. It demonstrates the
pipeline (evidence, references, validation, streaming); it is not an intelligence benchmark.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator
from typing import Any

from app.ai.evidence import Passage, rank
from app.ai.provider import ModelChunk, ModelRequest, TextChunk, UsageChunk
from app.domain.budget import Usage
from app.domain.catalog import product_mentioned

CHUNK_CHARS = 24
MODEL_NAME = 'fixture'


def _payload(request: ModelRequest, prefix: str) -> dict[str, Any]:
    for item in request.inputs:
        if item.text.startswith(prefix):
            data: dict[str, Any] = json.loads(item.text.removeprefix(prefix))
            return data
    raise ValueError(f'missing {prefix!r} input')


_EN_FOLLOW_UPS = ['What does the kit include?', 'Which ages is it for?']


def _answer(store: dict[str, Any], turn: dict[str, Any]) -> dict[str, Any]:
    answer = _spanish_answer(store, turn)
    if turn.get('reply_language') != 'en':
        return answer
    # The fixture cannot translate: it quotes the Spanish store text under an English lead-in.
    text = answer['answer'].removeprefix('Según la información de la tienda: ')
    if not answer['references'] or answer['references'][0]['kind'] == 'link':
        lead = "I don't have that information in the store data. You can write to support and the team will reply."
        return {**answer, 'answer': lead, 'follow_ups': _EN_FOLLOW_UPS}
    return {
        **answer,
        'answer': f'From the store information: {text}',
        'follow_ups': _EN_FOLLOW_UPS,
    }


def _spanish_answer(store: dict[str, Any], turn: dict[str, Any]) -> dict[str, Any]:
    question = turn['question'].lower()
    from app.domain.answer_policy import fold

    normalized = fold(question)
    selected = [
        p
        for p in store['products']
        if product_mentioned(
            question,
            p['name'],
            p['id'],
            p.get('kind', 'core'),
            tuple(r['id'].rsplit('/', 1)[-1] for r in p['resources']),
        )
    ]
    if len(selected) > 1:
        return {
            'answer': '\n'.join(f'{p["name"]}: {p["summary"]} Formato: {p["format"]}.' for p in selected),
            'references': [{'kind': 'product', 'id': p['id']} for p in selected],
            'sources': [],
            'follow_ups': [],
        }
    if not selected and len(store['products']) > 1:
        previous = next(
            (entry for entry in reversed(turn.get('conversation', [])) if entry.get('referenced_ids')), None
        )
        if previous:
            selected = [p for p in store['products'] if p['id'] in previous['referenced_ids']]
    if not selected and len(store['products']) > 1:
        return {
            'answer': '¿Te interesa Grafismo Fonético o la Guía de Alimentación para Bebés?',
            'references': [],
            'sources': [],
            'follow_ups': [],
        }
    product = selected[0] if selected else store['products'][0]
    if product.get('kind') == 'affiliate':
        price_question = any(w in normalized for w in ('precio', 'cuesta', 'price', 'cost'))
        text = (
            'No tengo un precio publicado para este producto; puedes consultar el importe vigente en Hotmart.'
            if price_question
            else f'{product["name"]}: {product["summary"]} {product["format"]}. '
            + ' '.join(product.get('topics', []))
        )
        return {
            'answer': text,
            'references': [{'kind': 'product', 'id': product['id']}],
            'sources': [d['id'] for d in store['documents'] if product['id'] in d.get('product_ids', [])][:2],
            'follow_ups': [],
        }
    support = next((link['id'] for link in store['links'] if 'soporte' in link['label'].lower()), None)
    items = [
        Passage(f'product:{product["id"]}', f'{product["name"]} {product["summary"]} {product["usage"]}')
    ]
    items += [
        Passage(f'resource:{r["id"]}', f'{r["title"]} {r["description"]}') for r in product['resources']
    ]
    items += [Passage(f'document:{d["id"]}', f'{d["title"]} {d["text"]}') for d in store['documents']]
    by_id = {p.id: p for p in items}
    ranked = [(p, s) for p, s in rank(turn['question'], items) if s > 0]
    if not ranked:
        return {
            'answer': 'No tengo esa información en los datos de la tienda. Si quieres, puedes escribirnos '
            'desde soporte y te respondemos.',
            'references': [{'kind': 'link', 'id': support}] if support else [],
            'sources': [],
            'follow_ups': ['¿Qué incluye el kit?', '¿Para qué edades es?'],
        }
    best = ranked[0][0]
    if best.id.startswith('document:'):
        document = next(d for d in store['documents'] if f'document:{d["id"]}' == best.id)
        text = document['text']
    elif best.id.startswith('resource:'):
        resource = next(r for r in product['resources'] if f'resource:{r["id"]}' == best.id)
        text = f'**{resource["title"]}**: {resource["description"]}'
    else:
        text = f'**{product["name"]}**: {product["summary"]}'
    resources = [p.id.removeprefix('resource:') for p, _ in ranked if p.id.startswith('resource:')][:2]
    sources = [p.id.removeprefix('document:') for p, _ in ranked if p.id.startswith('document:')][:2]
    follow_ups = [
        by_id[f'document:{d["id"]}'].text.split('?')[0] + '?'
        for d in store['documents']
        if d['kind'] == 'faq' and d['id'] not in sources and d['title'].endswith('?')
    ][:2]
    return {
        'answer': f'Según la información de la tienda: {text}',
        'references': [{'kind': 'product', 'id': product['id']}]
        + [{'kind': 'resource', 'id': r} for r in resources],
        'sources': sources,
        'follow_ups': follow_ups,
    }


class FixtureProvider:
    def __init__(self, chunk_delay_seconds: float = 0.0) -> None:
        self._delay = chunk_delay_seconds

    @property
    def model(self) -> str:
        return MODEL_NAME

    async def stream(self, request: ModelRequest) -> AsyncGenerator[ModelChunk]:
        store = _payload(request, 'store_data:\n')
        turn = _payload(request, 'visitor_turn:\n')
        output = json.dumps(_answer(store, turn), ensure_ascii=False)
        for start in range(0, len(output), CHUNK_CHARS):
            if self._delay:
                await asyncio.sleep(self._delay)
            yield TextChunk(output[start : start + CHUNK_CHARS])
        yield UsageChunk(Usage(input_tokens=request.size_bytes() // 4, output_tokens=len(output) // 4))
