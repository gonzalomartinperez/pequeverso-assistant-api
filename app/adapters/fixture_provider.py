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

CHUNK_CHARS = 24
MODEL_NAME = 'fixture'


def _payload(request: ModelRequest, prefix: str) -> dict[str, Any]:
    for item in request.inputs:
        if item.text.startswith(prefix):
            data: dict[str, Any] = json.loads(item.text.removeprefix(prefix))
            return data
    raise ValueError(f'missing {prefix!r} input')


def _answer(store: dict[str, Any], turn: dict[str, Any]) -> dict[str, Any]:
    product = store['products'][0]
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
