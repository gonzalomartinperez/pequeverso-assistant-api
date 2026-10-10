"""Stream lifecycle over a real socket: failures, timeouts, heartbeats, cancellation, disconnects."""

from __future__ import annotations

import asyncio
import sqlite3
import threading
import time
from contextlib import closing
from pathlib import Path

import httpx
import pytest

from app.application.sessions import SessionService
from app.domain.conversation import Session
from app.domain.errors import FailureCode
from tests.support import JSON_HEADERS, ORIGIN, ScriptedProvider, answer_json, live_server, parse_sse

GOOD = answer_json(
    'Respuesta completa del asistente sobre el kit.',
    references=[{'kind': 'product', 'id': 'grafismo-fonetico'}],
)


def _session(http: httpx.Client) -> str:
    response = http.post('/api/v1/session', headers=JSON_HEADERS, json={})
    assert response.status_code == 201
    token: str = response.json()['csrf_token']
    return token


def _headers(csrf: str, key: str) -> dict[str, str]:
    return {**JSON_HEADERS, 'X-CSRF-Token': csrf, 'Idempotency-Key': key}


def _ask(http: httpx.Client, csrf: str, key: str) -> list[dict[str, object]]:
    with http.stream('POST', '/api/v1/messages', headers=_headers(csrf, key), json={'content': 'Hola'}) as r:
        assert r.status_code == 200
        assert r.headers['cache-control'].startswith('no-cache') and r.headers['x-accel-buffering'] == 'no'
        return parse_sse(''.join(r.iter_text()))


def test_failures_and_timeouts_end_with_one_terminal_event(tmp_path: Path) -> None:
    for provider, overrides, code in (
        (ScriptedProvider(fail_with=FailureCode.PROVIDER_UNAVAILABLE), {}, 'provider_unavailable'),
        (ScriptedProvider(hang=True), {'run_timeout_seconds': 0.5}, 'timeout'),
        (ScriptedProvider(output='{"answer": "roto', usage=None), {}, 'generation_failed'),
    ):
        with (
            live_server(tmp_path / code, provider, **overrides) as url,
            httpx.Client(base_url=url, timeout=10) as http,
        ):
            csrf = _session(http)
            events = _ask(http, csrf, 'key-0000001')
            assert next(e['type'] for e in events) == 'run.started'
            assert events[-1]['type'] == 'run.failed' and events[-1]['code'] == code
            assert sum(e['type'] in ('run.completed', 'run.failed', 'run.cancelled') for e in events) == 1
            # The session is usable again: slot and active-run lock were released.
            provider.fail_with, provider.hang, provider.output, provider.usage = None, False, GOOD, None
            assert _ask(http, csrf, 'key-0000002')[-1]['type'] == 'run.completed'


def test_cancel_endpoint_stops_a_silent_provider_with_heartbeats(tmp_path: Path) -> None:
    provider = ScriptedProvider(hang=True)
    with (
        live_server(tmp_path, provider, heartbeat_seconds=0.2, run_timeout_seconds=20) as url,
        httpx.Client(base_url=url, timeout=10) as http,
    ):
        csrf = _session(http)
        chunks: list[str] = []
        run_id: list[str] = []

        def consume() -> None:
            with http.stream(
                'POST', '/api/v1/messages', headers=_headers(csrf, 'key-0000001'), json={'content': 'Hola'}
            ) as r:
                run_id.append(r.headers['x-run-id'])
                chunks.extend(r.iter_text())

        thread = threading.Thread(target=consume)
        thread.start()
        deadline = time.monotonic() + 5
        while not run_id and time.monotonic() < deadline:
            time.sleep(0.02)
        time.sleep(0.6)
        cancel = http.post(f'/api/v1/runs/{run_id[0]}/cancel', headers={**JSON_HEADERS, 'X-CSRF-Token': csrf})
        assert cancel.status_code == 202
        thread.join(5)
        body = ''.join(chunks)
        assert ': keep-alive' in body
        events = parse_sse(body)
        assert events[-1]['type'] == 'run.cancelled'
        assert provider.closed == 1
        assert (
            http.post(
                f'/api/v1/runs/{run_id[0]}/cancel', headers={**JSON_HEADERS, 'X-CSRF-Token': csrf}
            ).status_code
            == 404
        )


def test_client_disconnect_cancels_upstream_and_stores_nothing_partial(tmp_path: Path) -> None:
    provider = ScriptedProvider(output=GOOD, delay=0.05, chunk=2)
    with (
        live_server(tmp_path, provider, max_concurrent_runs=1) as url,
        httpx.Client(base_url=url, timeout=10) as http,
    ):
        csrf = _session(http)
        with http.stream(
            'POST', '/api/v1/messages', headers=_headers(csrf, 'key-0000001'), json={'content': 'Hola'}
        ) as r:
            for chunk in r.iter_text():
                if 'message.delta' in chunk:
                    break
        deadline = time.monotonic() + 5
        while provider.closed == 0 and time.monotonic() < deadline:
            time.sleep(0.02)
        assert provider.closed == 1
        provider.delay = 0
        # The single concurrency slot and the session's active-run lock were both released.
        assert _ask(http, csrf, 'key-0000002')[-1]['type'] == 'run.completed'
        history = http.post('/api/v1/session', headers=JSON_HEADERS, json={}).json()['messages']
        assert [m['role'] for m in history] == ['user', 'user', 'assistant']


def test_one_active_run_per_session_and_global_concurrency(tmp_path: Path) -> None:
    provider = ScriptedProvider(hang=True)
    with (
        live_server(tmp_path, provider, run_timeout_seconds=2, max_concurrent_runs=1) as url,
        httpx.Client(base_url=url, timeout=10) as http,
        httpx.Client(base_url=url, timeout=10) as other,
    ):
        csrf = _session(http)
        other_csrf = _session(other)
        started = threading.Event()

        def consume() -> None:
            with http.stream(
                'POST', '/api/v1/messages', headers=_headers(csrf, 'key-0000001'), json={'content': 'Hola'}
            ) as r:
                started.set()
                for _ in r.iter_text():
                    pass

        thread = threading.Thread(target=consume)
        thread.start()
        started.wait(5)
        same = http.post('/api/v1/messages', headers=_headers(csrf, 'key-0000002'), json={'content': 'Otra'})
        assert same.status_code == 409 and same.json()['error']['code'] == 'run_in_progress'
        busy = other.post(
            '/api/v1/messages', headers=_headers(other_csrf, 'key-0000003'), json={'content': 'Hola'}
        )
        assert (
            busy.status_code == 503 and busy.json()['error']['code'] == 'busy' and busy.headers['retry-after']
        )
        thread.join(6)


def test_origin_is_enforced_on_the_real_server(tmp_path: Path) -> None:
    with live_server(tmp_path) as url, httpx.Client(base_url=url, timeout=10) as http:
        assert (
            http.post(
                '/api/v1/session',
                headers={'Origin': 'https://evil.example', 'Content-Type': 'application/json'},
                json={},
            ).status_code
            == 403
        )
        assert (
            http.post(
                '/api/v1/session', headers={'Origin': ORIGIN, 'Content-Type': 'application/json'}, json={}
            ).status_code
            == 201
        )


def test_delete_cancels_silent_provider_before_erasing_session(tmp_path: Path) -> None:
    provider = ScriptedProvider(hang=True, usage=None)
    with (
        live_server(tmp_path, provider, max_concurrent_runs=1) as url,
        httpx.Client(base_url=url, timeout=10) as http,
    ):
        csrf = _session(http)
        started = threading.Event()
        chunks: list[str] = []

        def consume() -> None:
            with http.stream(
                'POST',
                '/api/v1/messages',
                headers=_headers(csrf, 'delete-active-001'),
                json={'content': 'Hola'},
            ) as response:
                assert response.status_code == 200
                started.set()
                chunks.extend(response.iter_text())

        thread = threading.Thread(target=consume)
        thread.start()
        assert started.wait(5)
        # The SSE headers precede the first provider anext: wait until the controlled
        # provider really started, so this tests cancellation of a live generation.
        deadline = time.monotonic() + 5
        while not provider.calls and time.monotonic() < deadline:
            time.sleep(0.01)
        assert len(provider.calls) == 1
        deleted = http.delete('/api/v1/session', headers={**JSON_HEADERS, 'X-CSRF-Token': csrf})
        assert deleted.status_code == 204
        thread.join(5)
        assert not thread.is_alive() and provider.closed == 1
        assert parse_sse(''.join(chunks))[-1]['type'] == 'run.cancelled'
        with closing(sqlite3.connect(tmp_path / 'test.sqlite3')) as database:
            assert database.execute('SELECT count(*) FROM sessions').fetchone()[0] == 0
            assert database.execute('SELECT count(*) FROM messages').fetchone()[0] == 0
            assert database.execute('SELECT count(*) FROM runs').fetchone()[0] == 0
            ledger = database.execute(
                'SELECT status,actual_micro,reserved_micro FROM spend_ledger'
            ).fetchone()
            assert ledger[0] == 'unreported' and ledger[1] is None and ledger[2] > 0
        provider.hang = False
        csrf = _session(http)
        assert _ask(http, csrf, 'delete-new-session-001')[-1]['type'] == 'run.completed'


def test_admission_revalidates_session_when_delete_wins_after_dependency_resolution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = ScriptedProvider()
    resolved = threading.Event()
    release = threading.Event()
    original = SessionService.require
    paused = False

    async def resolve_then_pause(self: SessionService, secret: str | None, csrf: str | None) -> Session:
        nonlocal paused
        session = await original(self, secret, csrf)
        if not paused:
            paused = True
            resolved.set()
            assert await asyncio.to_thread(release.wait, 5)
        return session

    monkeypatch.setattr(SessionService, 'require', resolve_then_pause)
    with live_server(tmp_path, provider) as url, httpx.Client(base_url=url, timeout=10) as http:
        csrf = _session(http)
        responses: list[httpx.Response] = []

        def ask_before_delete() -> None:
            responses.append(
                http.post(
                    '/api/v1/messages',
                    headers=_headers(csrf, 'delete-admission-001'),
                    json={'content': 'Hola'},
                )
            )

        thread = threading.Thread(target=ask_before_delete)
        thread.start()
        try:
            assert resolved.wait(5)
            deleted = http.delete('/api/v1/session', headers={**JSON_HEADERS, 'X-CSRF-Token': csrf})
            assert deleted.status_code == 204
        finally:
            release.set()
            thread.join(5)
        assert not thread.is_alive()
        assert responses[0].status_code == 401
        assert responses[0].json()['error']['code'] == 'session_expired'
        assert provider.calls == []
        with closing(sqlite3.connect(tmp_path / 'test.sqlite3')) as database:
            for query in (
                'SELECT count(*) FROM sessions',
                'SELECT count(*) FROM messages',
                'SELECT count(*) FROM runs',
                'SELECT count(*) FROM spend_ledger',
            ):
                assert database.execute(query).fetchone()[0] == 0


def test_touch_failure_after_admission_closes_run_without_provider_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = ScriptedProvider()

    async def fail_touch(self: SessionService, session: Session) -> None:
        raise RuntimeError('synthetic session persistence failure')

    monkeypatch.setattr(SessionService, 'touch', fail_touch)
    with live_server(tmp_path, provider) as url, httpx.Client(base_url=url, timeout=10) as http:
        csrf = _session(http)
        response = http.post(
            '/api/v1/messages', headers=_headers(csrf, 'touch-failure-001'), json={'content': 'Hola'}
        )
        assert response.status_code == 503
        assert response.json()['error']['code'] == 'dependency_unavailable'
        assert provider.calls == []
        with closing(sqlite3.connect(tmp_path / 'test.sqlite3')) as database:
            assert database.execute('SELECT state FROM runs').fetchone()[0] == 'cancelled'
            assert database.execute('SELECT status,actual_micro FROM spend_ledger').fetchone() == (
                'unreported',
                None,
            )
