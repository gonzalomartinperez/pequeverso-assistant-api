"""Conversational and guard evaluations through the full HTTP/SSE path.

Fixture mode (default, free, deterministic):
    uv run python scripts/evaluate_conversations.py

Live mode (paid; run only with explicit authorization). The spend cap is enforced by the
service's own budget ledger, which is set to --max-usd for the evaluation database:
    ALLOW_PAID_AI=true OPENAI_API_KEY=... \\
    uv run python scripts/evaluate_conversations.py --live --max-usd 0.25 --output docs/verification/live-eval.json

`safety` results are code-enforced guarantees and must pass in every mode. `quality` results
describe model behavior; in fixture mode they are reported but carry no meaning about a real
model.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient

from app.adapters.catalog_schema import CatalogParser
from app.ai.provider import ModelChunk, ModelRequest, TextChunk, UsageChunk
from app.application.answers import answer_rules
from app.bootstrap.config import DEFAULT_CATALOG, Settings
from app.bootstrap.container import create_app
from app.domain.answer_policy import check_answer, fold
from app.domain.budget import Usage
from app.domain.catalog import PriceStatus

ORIGIN = 'http://localhost:3000'
HEADERS = {'Origin': ORIGIN, 'Content-Type': 'application/json'}
HOSTS = frozenset(Settings.model_fields['catalog_allowed_hosts'].default)
CATALOG = CatalogParser(HOSTS)(DEFAULT_CATALOG.read_bytes())
TERMINAL = {'run.completed', 'run.failed', 'run.cancelled'}


class _Clock:
    def __init__(self, offset_days: int) -> None:
        self._base = max(datetime.now(UTC), CATALOG.generated_at) + timedelta(days=offset_days)

    def now(self) -> datetime:
        return self._base


class _ScriptedProvider:
    """A model that returns exactly the given structured output (guard evaluation)."""

    def __init__(self, output: dict[str, Any]) -> None:
        self._output = json.dumps(output, ensure_ascii=False)

    @property
    def model(self) -> str:
        return 'scripted'

    async def stream(self, request: ModelRequest) -> AsyncGenerator[ModelChunk]:
        for start in range(0, len(self._output), 16):
            yield TextChunk(self._output[start : start + 16])
        yield UsageChunk(Usage(input_tokens=request.size_bytes() // 4, output_tokens=len(self._output) // 4))


def _events(body: str) -> list[dict[str, Any]]:
    events = []
    for block in body.split('\n\n'):
        data = [line[6:] for line in block.split('\n') if line.startswith('data: ')]
        if data:
            events.append(json.loads(data[0]))
    return events


def _ask(
    client: TestClient, csrf: str, content: str, n: int
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    headers = {**HEADERS, 'X-CSRF-Token': csrf, 'Idempotency-Key': f'eval-{n:08d}'}
    with client.stream(
        'POST', '/api/v1/messages', headers=headers, json={'content': content, 'page': 'product'}
    ) as r:
        body = ''.join(r.iter_text())
    if r.status_code != 200:
        return [], {'http_status': r.status_code, 'error': json.loads(body)['error']['code']}
    return _events(body), None


def _safety(events: list[dict[str, Any]], price_status: PriceStatus) -> list[str]:
    problems: list[str] = []
    types = [e['type'] for e in events]
    if (
        not types
        or types[0] != 'run.started'
        or sum(t in TERMINAL for t in types) != 1
        or types[-1] not in TERMINAL
    ):
        problems.append(f'stream grammar: {types}')
    completed = [e for e in events if e['type'] == 'message.completed']
    if not completed:
        failed = [e.get('code') for e in events if e['type'] == 'run.failed']
        return [*problems, f'no answer (run.failed: {failed})']
    message = completed[0]['message']
    rules = answer_rules(CATALOG, price_status, ())
    if violations := check_answer(message['content'], rules):
        problems.append(f'final content violates rules: {violations}')
    for product in message['products']:
        if CATALOG.product(product['id']) is None:
            problems.append(f'unknown product {product["id"]}')
        if price_status is PriceStatus.UNVERIFIED and product['price'] is not None:
            problems.append('price shown while unverified')
    for resource in message['resources']:
        if CATALOG.resource(resource['id']) is None:
            problems.append(f'unknown resource {resource["id"]}')
    urls = [p['url'] for p in message['products']] + [p['purchase_url'] for p in message['products']]
    urls += [link['url'] for link in message['links']] + [s['url'] for s in message['sources']]
    for url in urls:
        if urlsplit(url).scheme != 'https' or urlsplit(url).hostname not in HOSTS:
            problems.append(f'unsafe url {url}')
    if '<' in message['content'] and '>' in message['content']:
        problems.append('markup in content')
    return problems


def _refs(message: dict[str, Any]) -> set[str]:
    refs = {f'product:{p["id"]}' for p in message['products']}
    refs |= {f'resource:{r["id"]}' for r in message['resources']}
    return refs | {f'link:{link["id"]}' for link in message['links']}


def _quality(message: dict[str, Any] | None, rules: dict[str, Any]) -> list[str]:
    if message is None:
        return ['no final message']
    problems: list[str] = []
    content = fold(message['content'])
    for ref in rules.get('must_reference', []):
        if ref not in _refs(message):
            problems.append(f'missing reference {ref}')
    if 'max_resources' in rules and len(message['resources']) > rules['max_resources']:
        problems.append('too many resources')
    if (any_of := rules.get('mentions_any')) and not any(fold(term) in content for term in any_of):
        problems.append(f'mentions none of {any_of}')
    for term in rules.get('forbid_any', []):
        if fold(term) in content:
            problems.append(f'mentions forbidden {term!r}')
    if rules.get('asks_question') and '?' not in message['content']:
        problems.append('asks no clarifying question')
    return problems


def run_conversations(settings: Settings, provider: Any = None) -> list[dict[str, Any]]:
    scenarios = json.loads((ROOT / 'evals' / 'conversations.json').read_text())['scenarios']
    results = []
    counter = 0
    for scenario in scenarios:
        clock = _Clock(scenario.get('clock_offset_days', 0))
        price_status = (
            PriceStatus.UNVERIFIED if scenario.get('clock_offset_days', 0) > 7 else PriceStatus.VERIFIED
        )
        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(
                settings.model_copy(update={'database_path': f'{tmp}/eval.sqlite3'}),
                provider=provider,
                clock=clock,
            )
            with TestClient(app, base_url='http://localhost:8000') as client:
                csrf = client.post('/api/v1/session', headers=HEADERS, json={}).json()['csrf_token']
                safety: list[str] = []
                final: dict[str, Any] | None = None
                for turn in scenario['turns']:
                    counter += 1
                    events, error = _ask(client, csrf, turn, counter)
                    if error:
                        safety.append(f'request refused: {error}')
                        continue
                    safety += _safety(events, price_status)
                    completed = [e for e in events if e['type'] == 'message.completed']
                    final = completed[0]['message'] if completed else None
        results.append(
            {
                'id': scenario['id'],
                'safety': safety,
                'quality': _quality(final, scenario.get('quality', {})),
                'answer': final['content'] if final else None,
                'references': sorted(_refs(final)) if final else [],
            }
        )
    return results


def run_guards(settings: Settings) -> list[dict[str, Any]]:
    cases = json.loads((ROOT / 'evals' / 'guards.json').read_text())['cases']
    results = []
    for n, case in enumerate(cases):
        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(
                settings.model_copy(update={'database_path': f'{tmp}/guard.sqlite3'}),
                provider=_ScriptedProvider(case['output']),
                clock=_Clock(0),
            )
            with TestClient(app, base_url='http://localhost:8000') as client:
                csrf = client.post('/api/v1/session', headers=HEADERS, json={}).json()['csrf_token']
                events, error = _ask(client, csrf, 'Pregunta de prueba', n)
        problems = [f'refused: {error}'] if error else _safety(events, PriceStatus.VERIFIED)
        message = next((e['message'] for e in events if e['type'] == 'message.completed'), None)
        expect = case['expect']
        if message is not None:
            replaced = 'answer_replaced' in message['notices']
            if replaced != expect['replaced']:
                problems.append(f'replaced={replaced}, expected {expect["replaced"]}')
            for key in ('products', 'resources', 'links', 'sources'):
                if key in expect and [item['id'] for item in message[key]] != expect[key]:
                    problems.append(f'{key}={[i["id"] for i in message[key]]}, expected {expect[key]}')
            if 'follow_ups' in expect and message['follow_ups'] != expect['follow_ups']:
                problems.append(f'follow_ups={message["follow_ups"]}')
            if 'content' in expect and message['content'] != expect['content']:
                problems.append(f'content={message["content"]!r}')
        results.append({'id': case['id'], 'problems': problems})
    return results


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        '--live', action='store_true', help='use the OpenAI provider (paid, needs authorization)'
    )
    parser.add_argument('--max-usd', default='0.25', help='budget cap for a live run, enforced by the ledger')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()

    base: dict[str, Any] = {
        'environment': 'test',
        'messages_per_session_per_day': 100,
        'messages_per_client_per_hour': 1000,
        'sessions_per_client_per_hour': 1000,
    }
    if args.live:
        if os.environ.get('ALLOW_PAID_AI', '').lower() != 'true' or not os.environ.get('OPENAI_API_KEY'):
            print('live evaluation needs ALLOW_PAID_AI=true and OPENAI_API_KEY (explicit authorization)')
            return 2
        base.update(
            ai_provider='openai',
            allow_paid_ai=True,
            openai_api_key=os.environ['OPENAI_API_KEY'],
            monthly_budget_usd=args.max_usd,
            daily_budget_usd=args.max_usd,
            budget_safety_margin='0',
        )
    settings = Settings(_env_file=None, **base)

    conversations = run_conversations(settings)
    guards = [] if args.live else run_guards(settings)
    summary: dict[str, int] = {
        'scenarios': len(conversations),
        'safety_failures': sum(bool(r['safety']) for r in conversations),
        'quality_failures': sum(bool(r['quality']) for r in conversations),
        'guard_cases': len(guards),
        'guard_failures': sum(bool(r['problems']) for r in guards),
    }
    report: dict[str, Any] = {
        'mode': 'live' if args.live else 'fixture',
        'model': settings.openai_model if args.live else 'fixture',
        'catalog_revision': CATALOG.source_revision,
        'conversations': conversations,
        'guards': guards,
        'summary': summary,
    }
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(text + '\n')
    print(json.dumps(summary))
    if not args.live:
        print(
            'note: fixture quality results say nothing about a real model; only safety and guards are gates.'
        )
    return 1 if summary['safety_failures'] or summary['guard_failures'] else 0


if __name__ == '__main__':
    sys.exit(main())
