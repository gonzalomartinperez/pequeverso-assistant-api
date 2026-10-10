"""Synthetic local model evaluation. Default is fixture; --live requires owner authorization.

Each phase shares one private persistent envelope. Never pass a key as an argument or env
assignment. Reports contain validated synthetic final answers, not provider payload/reasoning.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import stat
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))

from dotenv import dotenv_values
from fastapi.testclient import TestClient

from app.adapters.fixture_provider import FixtureProvider
from app.bootstrap.container import create_app
from app.domain.catalog import PriceStatus
from scripts import evaluate_conversations as conv
from scripts import evaluate_corpus as corpus
from scripts.real_eval_budget import BoundedProvider, Envelope


def run_case(case: dict[str, Any], provider: Any) -> dict[str, Any]:
    offset = int(case.get('clock_offset_days', 0))
    price_status = PriceStatus.UNVERIFIED if offset > 7 else PriceStatus.VERIFIED
    settings = corpus.settings_for_eval(assistant_enabled=True, ai_provider='fixture', allow_paid_ai=False)
    row: dict[str, Any] = {'id': case['id'], 'gates': [], 'answers': [], 'turns': []}
    with tempfile.TemporaryDirectory() as tmp:
        app = create_app(
            settings.model_copy(update={'database_path': f'{tmp}/case.sqlite3'}),
            provider=provider,
            clock=conv._Clock(offset),
        )
        with TestClient(app, base_url='http://localhost:8000') as client:
            csrf = client.post('/api/v1/session', headers=conv.HEADERS, json={}).json()['csrf_token']
            final = None
            for n, turn in enumerate(case['turns'], 1):
                before = time.monotonic()
                events, error = (
                    corpus._ask(client, csrf, case, turn, n)
                    if 'expect' in case
                    else conv._ask(client, csrf, turn, n)
                )
                row['turns'].append(
                    {
                        'elapsed_seconds': round(time.monotonic() - before, 3),
                        'event_types': [e['type'] for e in events],
                        'error': error,
                    }
                )
                if error:
                    row['gates'].append(f'request refused: {error["error"]}')
                    break
                row['gates'] += conv._safety(events, price_status)
                completed = [e for e in events if e['type'] == 'message.completed']
                final = completed[0]['message'] if completed else None
                if final:
                    row['answers'].append(final)
                started = next((e for e in events if e['type'] == 'run.started'), {})
                user_notices = started.get('user_message', {}).get('notices', [])
                for notice in case.get('expect', {}).get('user_notices', []):
                    if notice not in user_notices:
                        row['gates'].append(f'missing user-message notice {notice}')
                if row['gates'] or (
                    isinstance(provider, BoundedProvider) and provider.envelope.snapshot()['stop_reason']
                ):
                    break
            if 'expect' in case and final:
                row['language'] = corpus._language(case, final)
                row['behavior'], row['skipped'] = corpus._behavior(case, final, offset > 7)
                for notice in case['expect'].get('notices', []):
                    if notice not in final['notices']:
                        row['gates'].append(f'missing notice {notice}')
            else:
                row['quality'] = conv._quality(final, case.get('quality', {}))
    return row


def write_report(path: Path, report: dict[str, Any]) -> None:
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    temporary.chmod(0o600)
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--phase', choices=['conversations', 'dev', 'holdout'], required=True)
    parser.add_argument('--state-dir', type=Path, required=True)
    parser.add_argument('--key-file', type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    for name in ('httpx', 'httpx2', 'httpcore', 'httpcore2'):
        logging.getLogger(name).setLevel(logging.CRITICAL)
    logging.getLogger('openai').setLevel(logging.CRITICAL)
    state = args.state_dir.resolve()
    if state.is_relative_to(ROOT):
        raise ValueError('private state must be outside repository')
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    if stat.S_IMODE(state.stat().st_mode) != 0o700:
        raise ValueError('state directory must be private mode700')
    if args.phase == 'conversations':
        cases = json.loads((ROOT / 'evals/conversations.json').read_text())['scenarios']
    else:
        cases = [c for c in corpus.load() if c['split'] == args.phase]
    provider: Any = FixtureProvider()
    envelope = None
    if args.live:
        if args.key_file is None or stat.S_IMODE(args.key_file.stat().st_mode) != 0o600:
            raise ValueError('live key file must be private mode600')
        values = dotenv_values(args.key_file, interpolate=False)
        key = values.get('OPENAI_API_KEY')
        if (
            not key
            or values.get('OPENAI_MODEL') != 'gpt-6-luna'
            or values.get('OPENAI_REASONING_EFFORT') != 'medium'
        ):
            raise ValueError('private evaluation configuration does not match authorized model')
        envelope = Envelope(state / 'aggregate-budget.sqlite3')
        provider = BoundedProvider(key, envelope)
    report: dict[str, Any] = {
        'mode': 'live' if args.live else 'fixture',
        'model': provider.model,
        'phase': args.phase,
        'reasoning_effort': 'medium',
        'catalog_revision': conv.CATALOG.source_revision,
        'expected_cases': len(cases),
        'expected_turns': sum(len(c['turns']) for c in cases),
        'results': [],
        'stop_reason': None,
    }
    path = state / f'{report["mode"]}-{args.phase}.json'
    if path.exists():
        raise ValueError('phase report already exists; do not rerun paid cases')
    write_report(path, report)
    for case in cases:
        if envelope and (
            envelope.snapshot()['stop_reason']
            or envelope.snapshot()['reserved_micro_usd'] + 11000 > 1000000
            or envelope.snapshot()['attempts'] >= 400
        ):
            report['stop_reason'] = envelope.snapshot()['stop_reason'] or 'budget_or_attempt_limit'
            break
        row = run_case(case, provider)
        report['results'].append(row)
        if envelope:
            report['budget'] = envelope.snapshot()
            report['usage_receipts'] = provider.receipts
        if row['gates']:
            report['stop_reason'] = 'case_gate_failure'
            if envelope:
                envelope.stop('case_gate_failure')
        if envelope and envelope.snapshot()['stop_reason']:
            report['stop_reason'] = envelope.snapshot()['stop_reason']
        write_report(path, report)
        print(
            json.dumps(
                {
                    'phase': args.phase,
                    'completed': len(report['results']),
                    'expected': len(cases),
                    'stop_reason': report['stop_reason'],
                }
            ),
            flush=True,
        )
        if report['stop_reason']:
            break
    report['missing_ids'] = [c['id'] for c in cases[len(report['results']) :]]
    write_report(path, report)
    return 1 if report['stop_reason'] else 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as error:  # noqa: BLE001 -- redact all unexpected errors at secret boundary
        # Do not emit provider bodies, repr, str, tracebacks or private configuration.
        print(json.dumps({'outcome': 'stopped', 'error_type': type(error).__name__}))
        sys.exit(2)
