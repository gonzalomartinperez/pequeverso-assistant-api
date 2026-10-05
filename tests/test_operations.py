"""Languages over HTTP, ledger states (pending/settled/unreported) and the private ops summary."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import AsyncGenerator
from contextlib import closing
from pathlib import Path

from app.ai.provider import ModelChunk, ModelRequest, TextChunk, UsageChunk
from app.domain.budget import Usage
from app.domain.errors import FailureCode, RejectedError
from tests.support import JSON_HEADERS, FixedClock, ScriptedProvider, answer_json, ask, client, open_session

TOKEN = 'ops-test-token-0123456789abcdef0123456789'
AUTH = {'Authorization': f'Bearer {TOKEN}'}


def _ledger(tmp_path: Path) -> list[sqlite3.Row]:
    with closing(sqlite3.connect(tmp_path / 'test.sqlite3')) as c:
        c.row_factory = sqlite3.Row
        return list(c.execute('SELECT * FROM spend_ledger ORDER BY created_at'))


class IncompleteProvider:
    """Reports usage, then fails like a `response.incomplete` (reasoning used the allowance)."""

    model = 'scripted'

    async def stream(self, request: ModelRequest) -> AsyncGenerator[ModelChunk]:
        yield TextChunk('{"answer":"Ho')
        yield UsageChunk(Usage(input_tokens=3000, output_tokens=4000, reasoning_tokens=3990))
        raise RejectedError(FailureCode.GENERATION_FAILED)


def test_english_question_gets_an_english_answer_flagged_as_such(tmp_path: Path) -> None:
    provider = ScriptedProvider(output=answer_json('The kit includes 9 PDFs.'))
    with client(tmp_path, provider=provider) as c:
        csrf = open_session(c)
        status, events, _ = ask(c, csrf, 'What does the kit include?')
        assert status == 200
        final = events[-2]['message']
        assert final['language'] == 'en'
        assert '"reply_language":"en"' in provider.calls[0].inputs[1].text
        status, events, _ = ask(c, csrf, '¿Y para qué edades es?')
        assert events[-2]['message']['language'] == 'es'


def test_unsupported_language_answers_briefly_without_a_model_call_or_spend(tmp_path: Path) -> None:
    provider = ScriptedProvider()
    with client(tmp_path, provider=provider) as c:
        csrf = open_session(c)
        status, events, _ = ask(c, csrf, 'Quanto custa o kit para meu filho?')
        assert status == 200
        final = events[-2]['message']
        assert final['notices'] == ['language_unsupported']
        assert 'español' in final['content'] and 'English' in final['content']
        assert provider.calls == []
    assert _ledger(tmp_path) == []


def test_replacement_follows_the_reply_language(tmp_path: Path) -> None:
    provider = ScriptedProvider(output=answer_json('Use code SAVE20 for 20% off today only!'))
    with client(tmp_path, provider=provider) as c:
        csrf = open_session(c)
        _, events, _ = ask(c, csrf, 'Is there any discount code?')
        final = events[-2]['message']
        assert final['notices'] == ['answer_replaced']
        assert final['content'].startswith("I can't confirm") and final['language'] == 'en'


def test_starters_follow_the_requested_locale_and_the_catalog(tmp_path: Path) -> None:
    with client(tmp_path) as c:
        es = c.post('/api/v1/session', headers=JSON_HEADERS, json={}).json()
        assert 1 <= len(es['starters']) <= 4 and all(s.startswith('¿') for s in es['starters'])
        assert es['contract_revision'] == '1.1'
        en = c.post('/api/v1/session', headers=JSON_HEADERS, json={'locale': 'en'}).json()
        assert en['starters'][0] == 'What does Grafismo Fonético include?'
        assert c.post('/api/v1/session', headers=JSON_HEADERS, json={'locale': 'pt'}).status_code == 422


def test_ledger_settles_reported_usage_even_when_the_response_is_incomplete(tmp_path: Path) -> None:
    with client(tmp_path, provider=IncompleteProvider()) as c:
        csrf = open_session(c)
        _, events, _ = ask(c, csrf, '¿Qué incluye el kit?')
        assert events[-1]['type'] == 'run.failed'
    (row,) = _ledger(tmp_path)
    assert row['status'] == 'settled' and row['reasoning_tokens'] == 3990
    assert row['actual_micro'] == 2300  # 3000 x 0.10 + 4000 x 0.50 per 1M tokens


def test_failure_without_usage_keeps_the_reservation_as_an_estimate(tmp_path: Path) -> None:
    with client(tmp_path, provider=ScriptedProvider(fail_with=FailureCode.PROVIDER_UNAVAILABLE)) as c:
        csrf = open_session(c)
        _, events, _ = ask(c, csrf, '¿Qué incluye el kit?')
        assert events[-1]['type'] == 'run.failed'
    (row,) = _ledger(tmp_path)
    assert row['status'] == 'unreported' and row['actual_micro'] is None and row['reserved_micro'] > 0


def test_pending_reservations_of_a_dead_process_become_estimates(tmp_path: Path) -> None:
    with client(tmp_path):
        pass
    with closing(sqlite3.connect(tmp_path / 'test.sqlite3')) as c, c:
        c.execute(
            'INSERT INTO spend_ledger (run_id, month, day, reserved_micro, created_at, status)'
            " VALUES ('run_x', '2026-09', '2026-09-28', 99, '2026-09-28T12:00:00.000Z', 'pending')"
        )
    with client(tmp_path):
        pass
    assert _ledger(tmp_path)[0]['status'] == 'unreported'


def test_ops_summary_requires_a_configured_token(tmp_path: Path) -> None:
    with client(tmp_path) as c:
        assert c.get('/internal/v1/ops/summary', headers=AUTH).status_code == 404
    with client(tmp_path, ops_read_token=TOKEN) as c:
        assert c.get('/internal/v1/ops/summary').status_code == 401
        wrong = c.get('/internal/v1/ops/summary', headers={'Authorization': 'Bearer nope'})
        assert wrong.status_code == 401 and wrong.json()['error']['code'] == 'unauthorized'
        assert c.get('/api/v1/ops/summary', headers=AUTH).status_code == 404


def test_ops_summary_reports_aggregates_without_content(tmp_path: Path) -> None:
    clock = FixedClock()
    with client(tmp_path, provider=ScriptedProvider(), clock=clock, ops_read_token=TOKEN) as c:
        empty = c.get('/internal/v1/ops/summary', headers=AUTH).json()
        assert empty['metrics_since'] is None and empty['daily'] == []
        assert empty['windows'][0]['latency_ms'] == {'first_delta': None, 'total': None}
        csrf = open_session(c)
        ask(c, csrf, 'Mi hija Juana tiene 4 años, ¿qué incluye el kit?')
        ask(c, csrf, 'Quanto custa o kit para meu filho?')
        body = c.get('/internal/v1/ops/summary', headers=AUTH)
    assert body.headers['cache-control'] == 'no-store'
    summary = body.json()
    text = json.dumps(summary)
    assert 'Juana' not in text and 'Quanto' not in text and 'csrf' not in text
    day = summary['windows'][0]
    assert day['hours'] == 24 and day['runs']['completed'] == 2
    assert day['latency_ms']['total']['count'] == 1  # the unsupported-language reply made no model call
    assert day['tokens'] == {
        'input': 5000,
        'cached_input': 0,
        'output': 200,
        'reasoning': 0,
        'runs_with_usage': 1,
    }
    assert summary['budget']['month_spend'] == {
        'confirmed': '0.000600',
        'estimated': '0.000000',
        'pending': '0.000000',
    }
    assert summary['catalog']['status'] == 'active' and summary['catalog']['source'] == 'bundled'
    assert summary['service']['provider'] == 'fixture' and summary['service']['synthetic'] is True
    assert [d['day'] for d in summary['daily']] == ['2026-09-28']


def test_refusals_are_counted_as_refused(tmp_path: Path) -> None:
    with client(
        tmp_path,
        provider=ScriptedProvider(),
        ops_read_token=TOKEN,
        monthly_budget_usd='0.0001',
        daily_budget_usd='0.0001',
    ) as c:
        csrf = open_session(c)
        status, _, error = ask(c, csrf, '¿Qué incluye el kit?')
        assert status == 503 and error['error']['code'] == 'budget_exhausted'
        window = c.get('/internal/v1/ops/summary', headers=AUTH).json()['windows'][0]
    assert window['runs']['refused'] == 1 and window['failures'] == {'budget_exhausted': 1}
