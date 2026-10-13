"""Commercially rejected drafts must never leak through provisional HTTP/SSE content."""

import asyncio
import sqlite3
from collections.abc import AsyncGenerator
from contextlib import closing
from pathlib import Path

import httpx
import pytest

from app.ai.provider import ModelChunk, ModelRequest, TextChunk, UsageChunk
from app.application.answers import REPLACEMENT_ANSWER
from app.domain.budget import Usage
from app.domain.web_evidence import SOURCES, HelpTopic, WebEvidence
from tests.support import (
    CATALOG_BYTES,
    JSON_HEADERS,
    ScriptedProvider,
    answer_json,
    ask,
    client,
    live_server,
    mutation_headers,
    open_session,
    parse_sse,
)


@pytest.mark.parametrize(
    'answer',
    [
        'El kit cuesta $999 USD. Puedes comprarlo.',
        'El precio es $[999] USD. Puedes comprarlo.',
        'El precio es $<b>999</b> USD. Puedes comprarlo.',
        'He reembolsado tu compra. El dinero está enviado.',
        'El kit garantiza que tu hijo aprenderá a leer en siete días. Es seguro.',
        'Envíame tu tarjeta y CVV. Lo gestiono.',
        'Descarga https://pequeverso.com/private-orders/. Aquí está.',
    ],
)
def test_rejected_claims_split_per_character_never_reach_sse_history_or_replay(tmp_path, answer):
    provider = ScriptedProvider(answer_json(answer), chunk=1)
    with client(tmp_path, provider) as http:
        csrf = open_session(http)
        status, events, _ = ask(http, csrf, '¿Qué incluye el kit?', 'stream-safe-001')
        assert status == 200
        assert not any(e['type'] == 'message.delta' for e in events)
        final = events[-2]['message']
        assert final['content'] == REPLACEMENT_ANSWER
        assert final['notices'] == ['answer_replaced']
        restored = http.post('/api/v1/session', headers=JSON_HEADERS, json={}).json()['messages']
        assert restored[-1] == final
        _, replay, _ = ask(http, csrf, '¿Qué incluye el kit?', 'stream-safe-001')
        assert replay[-2]['message'] == final
        assert not any(e['type'] == 'message.delta' for e in replay)
        assert len(provider.calls) == 1
        http.cookies.clear()
        assert http.post('/api/v1/session', headers=JSON_HEADERS, json={}).json()['messages'] == []
    with closing(sqlite3.connect(tmp_path / 'test.sqlite3')) as db:
        assert db.execute('SELECT first_delta_ms FROM run_metrics').fetchone() == (None,)


@pytest.mark.parametrize(
    'answer',
    [
        'Tienes una garantía de 30 días para el kit. Es nuestra política.',
        'Tu compra es elegible para el reembolso. Se aprobará.',
        'Tu reembolso será aprobado. Está garantizado.',
        'Envíame tu número de transacción para solicitarlo. Yo lo gestiono.',
    ],
)
def test_selected_platform_evidence_does_not_authorize_unsafe_stream_claims(tmp_path, answer):
    from app.adapters.catalog_schema import CatalogParser

    catalog = CatalogParser(frozenset({'pequeverso.com', 'consumer.hotmart.com', 'refund.hotmart.com'}))(
        CATALOG_BYTES
    )
    source = next(s for s in SOURCES if s.topic is HelpTopic.REFUND)
    evidence = WebEvidence(
        source, 'Synthetic general procedure, not eligibility.', 'a' * 64, catalog.generated_at
    )

    class Reader:
        async def read(self, topics):
            return (evidence,)

    provider = ScriptedProvider(answer_json(answer), chunk=1)
    with client(tmp_path, provider) as http:
        http.app.state.services.chat.official_help = Reader()
        csrf = open_session(http)
        status, events, _ = ask(http, csrf, '¿Cómo solicitar un reembolso?')
        assert status == 200 and len(provider.calls) == 1
        assert not any(e['type'] == 'message.delta' for e in events)
        assert events[-2]['message']['notices'] == ['answer_replaced']


@pytest.mark.parametrize('price', ['$14.99 USD', 'US$14,99'])
def test_published_decimal_split_per_character_remains_complete_and_exact(tmp_path, price):
    text = f'El precio de referencia es {price}. Consulta el total final en Hotmart.'
    provider = ScriptedProvider(answer_json(text), chunk=1)
    with client(tmp_path, provider) as http:
        csrf = open_session(http)
        _, events, _ = ask(http, csrf, '¿Cuánto cuesta el kit?')
        pieces = [e['text'] for e in events if e['type'] == 'message.delta']
        assert pieces[0] == f'El precio de referencia es {price}.'
        assert ''.join(pieces) == text
        assert events[-2]['message']['content'] == text
        assert events[-2]['message']['notices'] == []
        restored = http.post('/api/v1/session', headers=JSON_HEADERS, json={}).json()['messages']
        assert restored[-1] == events[-2]['message']
        assert len(provider.calls) == 1


class GatedProvider:
    model = 'scripted'

    def __init__(self):
        self.calls = 0
        self.finished = False
        self.closed = False
        self.gate = None
        self.loop = None

    async def stream(self, request: ModelRequest) -> AsyncGenerator[ModelChunk]:
        self.calls += 1
        self.loop = asyncio.get_running_loop()
        self.gate = asyncio.Event()
        try:
            yield TextChunk('{"answer":"Puedes imprimir una hoja. ')
            await self.gate.wait()
            yield TextChunk('No necesitas imprimir todo.","references":[],"sources":[],"follow_ups":[]}')
            yield UsageChunk(Usage(input_tokens=5000, output_tokens=200))
            self.finished = True
        finally:
            self.closed = True

    def release(self):
        self.loop.call_soon_threadsafe(self.gate.set)


def test_valid_sentence_is_streamed_before_provider_finishes_over_real_socket(tmp_path: Path):
    provider = GatedProvider()
    with (
        live_server(tmp_path, provider) as url,
        httpx.Client(base_url=url, timeout=5, trust_env=False) as http,
    ):
        session = http.post('/api/v1/session', headers=JSON_HEADERS, json={})
        assert session.status_code == 201
        with http.stream(
            'POST',
            '/api/v1/messages',
            headers=mutation_headers(session.json()['csrf_token']),
            json={'content': '¿Tengo que imprimir todo?'},
        ) as response:
            assert response.status_code == 200
            blocks = []
            first_seen = False
            for line in response.iter_lines():
                blocks.append(line)
                if not first_seen and line.startswith('data: ') and '"message.delta"' in line:
                    first_seen = True
                    assert not provider.finished
                    assert 'Puedes imprimir una hoja.' in line
                    provider.release()
            events = parse_sse('\n'.join(blocks) + '\n')
        assert events[-1]['type'] == 'run.completed'
        assert events[-2]['message']['content'] == 'Puedes imprimir una hoja. No necesitas imprimir todo.'
        assert provider.calls == 1 and provider.finished


def test_safe_prefix_then_bad_sentence_is_held_and_final_replaced(tmp_path):
    provider = ScriptedProvider(answer_json('Es un kit imprimible. El kit cuesta $999 USD.'), chunk=1)
    with client(tmp_path, provider) as http:
        csrf = open_session(http)
        _, events, _ = ask(http, csrf, '¿Qué incluye el kit?')
        assert ''.join(e['text'] for e in events if e['type'] == 'message.delta') == 'Es un kit imprimible.'
        assert events[-2]['message']['content'] == REPLACEMENT_ANSWER
        assert events[-2]['message']['notices'] == ['answer_replaced']
        assert len(provider.calls) == 1


@pytest.mark.parametrize('known_usage', [True, False])
def test_disconnect_exactly_at_validated_final_tail_preserves_spend_not_partial_answer(tmp_path, known_usage):
    from app.application.chat import AnswerDelta, RunStarted

    provider = ScriptedProvider(
        answer_json('Puedes imprimir una hoja.'),
        usage=Usage(input_tokens=5000, output_tokens=200) if known_usage else None,
    )
    with client(tmp_path, provider) as http:
        csrf = open_session(http)
        services = http.app.state.services
        secret = http.cookies.get(services.settings.cookie.name)

        async def interrupt_tail():
            session = await services.sessions.require(secret, csrf)
            run = await services.chat.start(
                session, '¿Cómo se imprime?', None, 'tail-close-001', 'fixture-client'
            )
            stream = run.events()
            assert isinstance(await anext(stream), RunStarted)
            delta = await anext(stream)
            assert isinstance(delta, AnswerDelta) and delta.text == 'Puedes imprimir una hoja.'
            await stream.aclose()
            await run.aclose()
            await run.aclose()  # cleanup must be idempotent, including settlement.
            assert not len(services.chat.registry)

        http.portal.call(interrupt_tail)
        history = http.post('/api/v1/session', headers=JSON_HEADERS, json={}).json()['messages']
        assert [m['role'] for m in history] == ['user']
        assert provider.closed == 1 and len(provider.calls) == 1
    with closing(sqlite3.connect(tmp_path / 'test.sqlite3')) as db:
        status, actual, reserved, tokens = db.execute(
            'SELECT status,actual_micro,reserved_micro,input_tokens FROM spend_ledger'
        ).fetchone()
        if known_usage:
            assert status == 'settled' and actual > 0 and tokens == 5000
        else:
            assert status == 'unreported' and actual is None and reserved > 0 and tokens is None
        assert db.execute('SELECT count(*) FROM spend_ledger').fetchone() == (1,)


def test_cancel_after_final_tail_preserves_known_usage_and_never_commits_answer(tmp_path):
    from app.application.chat import AnswerDelta, RunCancelled, RunStarted

    provider = ScriptedProvider(answer_json('Puedes imprimir una hoja.'))
    with client(tmp_path, provider) as http:
        csrf = open_session(http)
        services = http.app.state.services
        secret = http.cookies.get(services.settings.cookie.name)

        async def cancel_tail():
            session = await services.sessions.require(secret, csrf)
            run = await services.chat.start(
                session, '¿Cómo se imprime?', None, 'tail-cancel-001', 'fixture-client'
            )
            stream = run.events()
            assert isinstance(await anext(stream), RunStarted)
            assert isinstance(await anext(stream), AnswerDelta)
            assert services.chat.registry.cancel(run.id, session.id)
            assert isinstance(await anext(stream), RunCancelled)
            with pytest.raises(StopAsyncIteration):
                await anext(stream)
            await stream.aclose()
            await run.aclose()
            assert not len(services.chat.registry)

        http.portal.call(cancel_tail)
        restored = http.post('/api/v1/session', headers=JSON_HEADERS, json={}).json()['messages']
        assert [m['role'] for m in restored] == ['user']
        assert provider.closed == 1 and len(provider.calls) == 1
    with closing(sqlite3.connect(tmp_path / 'test.sqlite3')) as db:
        assert db.execute('SELECT status,input_tokens FROM spend_ledger').fetchone() == ('settled', 5000)
        assert db.execute('SELECT state FROM runs').fetchone() == ('cancelled',)


@pytest.mark.parametrize('stop', ['cancel', 'timeout'])
def test_cancel_and_timeout_after_safe_prefix_never_persist_partial_history(tmp_path, stop):
    provider = GatedProvider()
    with (
        live_server(tmp_path, provider, run_timeout_seconds=1) as url,
        httpx.Client(base_url=url, timeout=5, trust_env=False) as http,
    ):
        session = http.post('/api/v1/session', headers=JSON_HEADERS, json={}).json()
        with http.stream(
            'POST',
            '/api/v1/messages',
            headers=mutation_headers(session['csrf_token']),
            json={'content': '¿Cómo se imprime?'},
        ) as response:
            blocks = []
            for line in response.iter_lines():
                blocks.append(line)
                if line.startswith('data: ') and '"message.delta"' in line and stop == 'cancel':
                    cancelled = http.post(
                        f'/api/v1/runs/{response.headers["x-run-id"]}/cancel',
                        headers={**JSON_HEADERS, 'X-CSRF-Token': session['csrf_token']},
                    )
                    assert cancelled.status_code == 202
            events = parse_sse('\n'.join(blocks) + '\n')
        assert events[-1]['type'] == ('run.cancelled' if stop == 'cancel' else 'run.failed')
        if stop == 'timeout':
            assert events[-1]['code'] == 'timeout'
        assert not any(e['type'] == 'message.completed' for e in events)
        history = http.post('/api/v1/session', headers=JSON_HEADERS, json={}).json()['messages']
        assert [m['role'] for m in history] == ['user']
        assert provider.closed and not provider.finished and provider.calls == 1


def test_deadline_after_final_tail_preserves_known_usage_without_persisting_answer(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from app.application import chat as chat_module
    from app.application.chat import AnswerDelta, RunFailed

    ticks = {'now': 100.0}
    monkeypatch.setattr(chat_module, 'time', SimpleNamespace(monotonic=lambda: ticks['now']))
    provider = ScriptedProvider(answer_json('Puedes imprimir una hoja.'))
    with client(tmp_path, provider, run_timeout_seconds=1) as http:
        csrf = open_session(http)
        services = http.app.state.services
        secret = http.cookies.get(services.settings.cookie.name)

        async def expire_tail():
            session = await services.sessions.require(secret, csrf)
            run = await services.chat.start(
                session, '¿Cómo se imprime?', None, 'tail-timeout-001', 'fixture-client'
            )
            stream = run.events()
            await anext(stream)
            assert isinstance(await anext(stream), AnswerDelta)
            ticks['now'] = 102.0
            failed = await anext(stream)
            assert isinstance(failed, RunFailed) and failed.code.value == 'timeout'
            await stream.aclose()
            await run.aclose()
            assert not len(services.chat.registry)

        http.portal.call(expire_tail)
        restored = http.post('/api/v1/session', headers=JSON_HEADERS, json={}).json()['messages']
        assert [m['role'] for m in restored] == ['user']
    with closing(sqlite3.connect(tmp_path / 'test.sqlite3')) as db:
        assert db.execute('SELECT status,input_tokens FROM spend_ledger').fetchone() == ('settled', 5000)


@pytest.mark.parametrize('stop', ['cancel', 'timeout'])
def test_stop_during_known_usage_settlement_stops_before_final_tail(tmp_path, monkeypatch, stop):
    from types import SimpleNamespace

    from app.application import chat as chat_module
    from app.application.chat import RunCancelled, RunFailed

    ticks = {'now': 100.0}
    if stop == 'timeout':
        monkeypatch.setattr(chat_module, 'time', SimpleNamespace(monotonic=lambda: ticks['now']))

    provider = ScriptedProvider(answer_json('Puedes imprimir una hoja.'))
    with client(tmp_path, provider, run_timeout_seconds=1) as http:
        csrf = open_session(http)
        services = http.app.state.services
        secret = http.cookies.get(services.settings.cookie.name)
        settle = services.chat.ledger.settle

        async def cancel_before_tail():
            session = await services.sessions.require(secret, csrf)

            async def settle_then_cancel(run_id, actual, usage, model):
                await settle(run_id, actual, usage, model)
                if stop == 'cancel':
                    assert services.chat.registry.cancel(run_id, session.id)
                else:
                    ticks['now'] = 102.0

            monkeypatch.setattr(services.chat.ledger, 'settle', settle_then_cancel)
            run = await services.chat.start(
                session, '¿Cómo se imprime?', None, 'pre-tail-cancel', 'fixture-client'
            )
            stream = run.events()
            await anext(stream)
            terminal = await anext(stream)
            if stop == 'cancel':
                assert isinstance(terminal, RunCancelled)
            else:
                assert isinstance(terminal, RunFailed) and terminal.code.value == 'timeout'
            await stream.aclose()
            await run.aclose()
            assert not len(services.chat.registry)

        http.portal.call(cancel_before_tail)
        history = http.post('/api/v1/session', headers=JSON_HEADERS, json={}).json()['messages']
        assert [m['role'] for m in history] == ['user']
    with closing(sqlite3.connect(tmp_path / 'test.sqlite3')) as db:
        assert db.execute('SELECT status,input_tokens FROM spend_ledger').fetchone() == ('settled', 5000)
        assert db.execute('SELECT first_delta_ms FROM run_metrics').fetchone() == (None,)


@pytest.mark.parametrize('length', [2000, 2001])
def test_existing_answer_bound_also_bounds_streaming_and_terminal_content(tmp_path, length):
    text = 'a' * (length - 1) + '.'
    with client(tmp_path, ScriptedProvider(answer_json(text), chunk=199)) as http:
        _, events, _ = ask(http, open_session(http), '¿Qué incluye?')
        streamed = ''.join(e['text'] for e in events if e['type'] == 'message.delta')
        if length == 2000:
            assert streamed == text and events[-2]['message']['content'] == text
        else:
            assert streamed == '' and events[-2]['message']['content'] == REPLACEMENT_ANSWER
            assert events[-2]['message']['notices'] == ['answer_replaced']


def test_later_markup_is_terminal_only_and_does_not_rewrite_emitted_prefix(tmp_path):
    provider = ScriptedProvider(answer_json('Primera frase. <b>Segunda frase.</b>'), chunk=1)
    with client(tmp_path, provider) as http:
        _, events, _ = ask(http, open_session(http), '¿Qué incluye?')
        assert ''.join(e['text'] for e in events if e['type'] == 'message.delta') == 'Primera frase.'
        assert events[-2]['message']['content'] == 'Primera frase. Segunda frase.'
        assert events[-2]['message']['notices'] == []
