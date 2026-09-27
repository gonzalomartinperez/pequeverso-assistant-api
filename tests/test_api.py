"""HTTP/SSE contract, session ownership, failure modes and abuse controls, against a real SQLite file."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import TypeAdapter

from app.presentation.events import StreamEvent
from app.presentation.schemas import SessionOut
from tests.support import (
    JSON_HEADERS,
    FixedClock,
    ScriptedProvider,
    answer_json,
    ask,
    client,
    mutation_headers,
    open_session,
)

EVENTS = TypeAdapter(StreamEvent)
GOOD = answer_json(
    'El kit incluye 9 PDF. Para 4 años, empieza por **Los Sonidos de Mi Casa**.',
    references=[
        {'kind': 'product', 'id': 'grafismo-fonetico'},
        {'kind': 'resource', 'id': 'grafismo-fonetico/sonidos-de-mi-casa'},
        {'kind': 'product', 'id': 'kit-que-no-existe'},
    ],
    sources=['faq.grafismo-fonetico.05'],
    follow_ups=['¿Cuánto tiempo por día?'],
)


def _types(events: list[dict[str, object]]) -> list[object]:
    return [e['type'] for e in events]


def test_session_create_restore_and_cookie_flags(tmp_path: Path) -> None:
    with client(tmp_path) as c:
        first = c.post('/api/v1/session', headers=JSON_HEADERS, json={})
        assert first.status_code == 201
        SessionOut.model_validate(first.json())
        cookie = first.headers['set-cookie']
        assert 'HttpOnly' in cookie and 'SameSite=lax' in cookie and 'Path=/' in cookie
        assert 'Domain=' not in cookie
        again = c.post('/api/v1/session', headers=JSON_HEADERS, json={})
        assert again.status_code == 200
        assert again.json()['csrf_token'] == first.json()['csrf_token']
        assert again.json()['created'] is False


def test_production_cookie_uses_host_prefix_and_secure(tmp_path: Path) -> None:
    overrides = {
        'environment': 'production',
        'ai_provider': 'openai',
        'allow_paid_ai': True,
        'openai_api_key': 'sk-test',
        'session_cookie_secure': True,
        'allowed_origins': ['https://assistant.pequeverso.com'],
        'client_hash_key': 'k' * 40,
    }
    from app.bootstrap.config import Settings
    from app.bootstrap.container import create_app

    app = create_app(Settings(_env_file=None, database_path=str(tmp_path / 'p.sqlite3'), **overrides))  # type: ignore[call-arg, arg-type]
    from fastapi.testclient import TestClient

    with TestClient(app, base_url='https://assistant.pequeverso.com') as c:
        response = c.post(
            '/api/v1/session',
            headers={'Origin': 'https://assistant.pequeverso.com', 'Content-Type': 'application/json'},
            json={},
        )
        assert response.status_code == 201
        cookie = response.headers['set-cookie']
        assert cookie.startswith('__Host-pv_assistant=') and 'Secure' in cookie
        assert c.get('/api/v1/openapi.json').status_code == 404


@pytest.mark.parametrize(
    'overrides',
    [
        {'ai_provider': 'openai'},
        {'ai_provider': 'openai', 'allow_paid_ai': True},
        {'environment': 'production'},
        {'environment': 'production', 'ai_provider': 'openai', 'allow_paid_ai': True, 'openai_api_key': 'k'},
        {'allowed_origins': ['https://assistant.pequeverso.com/embed']},
        {'daily_budget_usd': '20'},
    ],
)
def test_configuration_fails_closed(overrides: dict[str, object]) -> None:
    from app.bootstrap.config import Settings

    with pytest.raises(ValueError):  # noqa: PT011
        Settings(_env_file=None, **overrides)  # type: ignore[call-arg, arg-type]


def test_origin_content_type_and_body_limits(tmp_path: Path) -> None:
    with client(tmp_path) as c:
        denied = c.post(
            '/api/v1/session',
            headers={'Origin': 'https://evil.example', 'Content-Type': 'application/json'},
            json={},
        )
        assert denied.status_code == 403 and denied.json()['error']['code'] == 'origin_denied'
        assert (
            c.post('/api/v1/session', headers={'Content-Type': 'application/json'}, json={}).status_code
            == 403
        )
        form = c.post(
            '/api/v1/session',
            headers={'Origin': JSON_HEADERS['Origin'], 'Content-Type': 'text/plain'},
            content='{}',
        )
        assert form.status_code == 422
        csrf = open_session(c)
        huge = c.post(
            '/api/v1/messages', headers=mutation_headers(csrf), content=b'{"content":"' + b'a' * 20000 + b'"}'
        )
        assert huge.status_code == 422 and huge.json()['error']['code'] == 'invalid_request'


def test_cors_allows_only_configured_origins(tmp_path: Path) -> None:
    with client(tmp_path) as c:
        ok = c.options(
            '/api/v1/session',
            headers={'Origin': 'http://localhost:3000', 'Access-Control-Request-Method': 'POST'},
        )
        assert ok.headers.get('access-control-allow-origin') == 'http://localhost:3000'
        bad = c.options(
            '/api/v1/session',
            headers={'Origin': 'https://evil.example', 'Access-Control-Request-Method': 'POST'},
        )
        assert 'access-control-allow-origin' not in bad.headers


def test_stream_contract_validated_references_and_history(tmp_path: Path) -> None:
    provider = ScriptedProvider(output=GOOD)
    with client(tmp_path, provider) as c:
        csrf = open_session(c)
        status, events, _ = ask(c, csrf, 'Mi hijo tiene 4 años, ¿por dónde empiezo?', page='product')
        assert status == 200
        for event in events:
            EVENTS.validate_python(event)
        types = _types(events)
        assert types[0] == 'run.started' and types[-2:] == ['message.completed', 'run.completed']
        assert 'message.delta' in types
        assert [e['sequence'] for e in events] == list(range(len(events)))
        streamed = ''.join(str(e['text']) for e in events if e['type'] == 'message.delta')
        final = events[-2]['message']
        assert streamed == final['content']
        assert [p['id'] for p in final['products']] == ['grafismo-fonetico']
        assert final['products'][0]['price']['display'] == 'US$14,99'
        assert [r['id'] for r in final['resources']] == ['grafismo-fonetico/sonidos-de-mi-casa']
        assert final['sources'][0]['url'].startswith('https://pequeverso.com/')
        request = provider.calls[0]
        assert 'kit-que-no-existe' not in json.dumps(final)
        assert request.max_output_tokens == 1200
        assert 'store_data' in request.inputs[0].text and '"page":"product"' in request.inputs[1].text

        ask(c, csrf, '¿Y el segundo que mencionaste?')
        follow_up = json.loads(provider.calls[1].inputs[1].text.removeprefix('visitor_turn:\n'))
        assert [m['role'] for m in follow_up['conversation']] == ['user', 'assistant']
        assert 'grafismo-fonetico/sonidos-de-mi-casa' in follow_up['conversation'][1]['referenced_ids']

        restored = c.post('/api/v1/session', headers=JSON_HEADERS, json={}).json()
        assert [m['role'] for m in restored['messages']] == ['user', 'assistant', 'user', 'assistant']


def test_sessions_are_isolated(tmp_path: Path) -> None:
    with client(tmp_path, ScriptedProvider(output=GOOD)) as alice:
        csrf_a = open_session(alice)
        ask(alice, csrf_a, 'Hola')
        from fastapi.testclient import TestClient

        bob = TestClient(
            alice.app, base_url='http://localhost:8000'
        )  # shares the running app, own cookie jar
        if True:
            csrf_b = open_session(bob)
            assert csrf_b != csrf_a
            assert bob.post('/api/v1/session', headers=JSON_HEADERS, json={}).json()['messages'] == []
            # Alice's CSRF token is useless with Bob's cookie.
            status, _, error = ask(bob, csrf_a, 'Hola')
            assert status == 403 and error['error']['code'] == 'csrf_failed'


def test_mutations_require_session_and_csrf(tmp_path: Path) -> None:
    with client(tmp_path) as c:
        status, _, error = ask(c, 'no-session', 'Hola')
        assert status == 401 and error['error']['code'] == 'session_expired'
        open_session(c)
        status, _, error = ask(c, 'wrong-token', 'Hola')
        assert status == 403 and error['error']['code'] == 'csrf_failed'
        missing_key = c.post(
            '/api/v1/messages', headers={**JSON_HEADERS, 'X-CSRF-Token': 'x'}, json={'content': 'a'}
        )
        assert missing_key.status_code in (403, 422)


def test_idempotent_replay_and_conflict(tmp_path: Path) -> None:
    provider = ScriptedProvider(output=GOOD)
    with client(tmp_path, provider) as c:
        csrf = open_session(c)
        _, first, _ = ask(c, csrf, 'Hola', key='key-00000001')
        _, replay, _ = ask(c, csrf, 'Hola', key='key-00000001')
        assert len(provider.calls) == 1
        assert replay[0]['user_message'] is None
        assert replay[-2]['message'] == first[-2]['message']
        status, _, error = ask(c, csrf, 'Otra pregunta', key='key-00000001')
        assert status == 409 and error['error']['code'] == 'idempotency_conflict'


def test_session_expiry_and_deletion(tmp_path: Path) -> None:
    clock = FixedClock()
    with client(tmp_path, ScriptedProvider(output=GOOD), clock=clock) as c:
        csrf = open_session(c)
        ask(c, csrf, 'Hola')
        clock.advance(hours=25)
        status, _, error = ask(c, csrf, 'Hola de nuevo')
        assert status == 401 and error['error']['code'] == 'session_expired'
        fresh = c.post('/api/v1/session', headers=JSON_HEADERS, json={})
        assert fresh.status_code == 201 and fresh.json()['messages'] == []
        csrf = fresh.json()['csrf_token']
        ask(c, csrf, 'Hola')
        deleted = c.delete('/api/v1/session', headers={**JSON_HEADERS, 'X-CSRF-Token': csrf})
        assert deleted.status_code == 204 and 'Max-Age=0' in deleted.headers['set-cookie']
        status, _, _ = ask(c, csrf, 'Hola')
        assert status == 401


def test_card_numbers_never_reach_the_model_or_storage(tmp_path: Path) -> None:
    provider = ScriptedProvider(output=GOOD)
    with client(tmp_path, provider) as c:
        csrf = open_session(c)
        _, events, _ = ask(c, csrf, 'Quiero pagar con 4111 1111 1111 1111 exp 12/29')
        assert provider.calls == []
        assert events[0]['user_message']['content'].startswith('[mensaje eliminado')
        assert events[-2]['message']['notices'] == ['payment_data_refused']
        raw = (tmp_path / 'test.sqlite3').read_bytes() + (tmp_path / 'test.sqlite3-wal').read_bytes()
        assert b'4111 1111' not in raw


def test_contact_data_is_redacted_before_the_model(tmp_path: Path) -> None:
    provider = ScriptedProvider(output=GOOD)
    with client(tmp_path, provider) as c:
        csrf = open_session(c)
        _, events, _ = ask(c, csrf, 'Soy ana@example.com, ¿qué incluye?')
        assert 'ana@example.com' not in provider.calls[0].inputs[1].text
        assert events[0]['user_message']['notices'] == ['contact_data_redacted']


def test_rate_limits(tmp_path: Path) -> None:
    with client(
        tmp_path,
        ScriptedProvider(output=GOOD),
        messages_per_session_per_day=2,
        sessions_per_client_per_hour=2,
    ) as c:
        csrf = open_session(c)
        assert ask(c, csrf, 'Uno')[0] == 200
        assert ask(c, csrf, 'Dos')[0] == 200
        status, _, error = ask(c, csrf, 'Tres')
        assert status == 429 and error['error']['code'] == 'rate_limited'
    with client(tmp_path / 'b', sessions_per_client_per_hour=2) as c:
        for _ in range(2):
            c.cookies.clear()
            assert c.post('/api/v1/session', headers=JSON_HEADERS, json={}).status_code == 201
        c.cookies.clear()
        blocked = c.post('/api/v1/session', headers=JSON_HEADERS, json={})
        assert blocked.status_code == 429 and blocked.headers['retry-after']


def test_budget_exhaustion_is_graceful(tmp_path: Path) -> None:
    provider = ScriptedProvider(output=GOOD)
    with client(tmp_path, provider, daily_budget_usd='0.0005', monthly_budget_usd='10') as c:
        csrf = open_session(c)
        status, _, error = ask(c, csrf, 'Hola')
        assert status == 503 and error['error']['code'] == 'budget_exhausted'
        assert provider.calls == []
        assert c.get('/api/v1/availability').json() == {'status': 'unavailable', 'reason': 'budget_exhausted'}


def test_disabled_and_unavailable_catalog(tmp_path: Path) -> None:
    with client(tmp_path, assistant_enabled=False) as c:
        assert c.get('/api/v1/availability').json()['reason'] == 'assistant_disabled'
        csrf = open_session(c)
        assert ask(c, csrf, 'Hola')[2]['error']['code'] == 'assistant_disabled'
    with client(tmp_path / 'x', catalog_file=tmp_path / 'missing.json') as c:
        assert c.get('/health/ready').status_code == 503
        assert c.get('/health/live').status_code == 200
        csrf = open_session(c)
        assert ask(c, csrf, 'Hola')[2]['error']['code'] == 'catalog_unavailable'


def test_stale_prices_are_withheld_everywhere(tmp_path: Path) -> None:
    clock = FixedClock()
    clock.advance(days=30)
    quoted = answer_json('Cuesta US$14,99.', references=[{'kind': 'product', 'id': 'grafismo-fonetico'}])
    provider = ScriptedProvider(output=quoted)
    with client(tmp_path, provider, clock=clock) as c:
        csrf = open_session(c)
        _, events, _ = ask(c, csrf, '¿Cuánto cuesta?')
        store = provider.calls[0].inputs[0].text
        assert '"price_status":"unverified"' in store and 'US$14,99' not in store
        final = events[-2]['message']
        assert final['notices'] == ['answer_replaced']
        assert c.get('/health/ready').json()['catalog']['price_status'] == 'unverified'
        provider.output = answer_json(
            'El precio actual está en la página del kit.',
            references=[{'kind': 'product', 'id': 'grafismo-fonetico'}],
        )
        _, events, _ = ask(c, csrf, '¿Y el precio?')
        assert events[-2]['message']['products'][0]['price'] is None


def test_public_errors_never_leak_internals(tmp_path: Path) -> None:
    with client(tmp_path) as c:
        response = c.get('/api/v1/nope')
        assert response.status_code == 404
        assert set(response.json()['error']) == {'code', 'message', 'retryable', 'request_id'}
        assert response.headers['x-request-id']
        assert response.headers['cache-control'] == 'no-store'
