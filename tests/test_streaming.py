"""Stream lifecycle over a real socket: failures, timeouts, heartbeats, cancellation, disconnects."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import httpx

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
