"""SIGTERM over real HTTP/SSE sockets must finish persistence before closing SQLite."""

from __future__ import annotations

import signal
import socket
import sqlite3
import subprocess
import sys
import threading
import time
from contextlib import closing
from pathlib import Path

import httpx

from tests.support import JSON_HEADERS, parse_sse

ROOT = Path(__file__).resolve().parents[1]
SERVER = """
import sys
import uvicorn
from app.bootstrap.config import Settings
from app.bootstrap.container import create_app
settings = Settings(_env_file=None, environment='test', database_path=sys.argv[1],
                    fixture_chunk_delay_ms=int(sys.argv[3]), run_timeout_seconds=30)
app = create_app(settings)
uvicorn.run(app, host='127.0.0.1', port=int(sys.argv[2]), log_config=None,
            timeout_graceful_shutdown=0.3, access_log=False)
"""


def _start(database: Path, port: int, delay: int, output: Path) -> subprocess.Popen[bytes]:
    # Deliberately exclude ambient provider configuration/secrets from the child.
    with output.open('ab') as log:
        process = subprocess.Popen(  # noqa: S603 - fixed Python program, isolated fixture paths/port
            [sys.executable, '-c', SERVER, str(database), str(port), str(delay)],
            cwd=ROOT,
            env={'PATH': str(Path(sys.executable).parent)},
            stdout=log,
            stderr=subprocess.STDOUT,
        )
    try:
        deadline = time.monotonic() + 10
        with httpx.Client(timeout=0.5, trust_env=False) as probe:
            while time.monotonic() < deadline:
                assert process.poll() is None
                try:
                    response = probe.get(f'http://127.0.0.1:{port}/health/ready')
                    if response.status_code == 200:
                        return process
                except httpx.TransportError:
                    pass
                time.sleep(0.02)
        raise AssertionError('isolated subprocess did not become ready')
    except BaseException:
        process.terminate()
        process.wait(5)
        raise


def _stop(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is None:
        process.terminate()
    # Uvicorn's programmatic runner re-emits captured SIGTERM after graceful
    # teardown. Persistence assertions below distinguish cleanup from raw kill.
    assert process.wait(5) in (0, -signal.SIGTERM)


def test_sigterm_active_stream_drains_run_and_unknown_spend_before_restart(tmp_path: Path) -> None:
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
    database = tmp_path / 'assistant.sqlite3'
    process = _start(database, port, 2000, tmp_path / 'server.log')
    thread: threading.Thread | None = None
    chunks: list[str] = []
    try:
        with httpx.Client(base_url=f'http://127.0.0.1:{port}', timeout=10) as http:
            session = http.post('/api/v1/session', headers=JSON_HEADERS, json={})
            assert session.status_code == 201
            csrf = session.json()['csrf_token']
            started = threading.Event()

            def consume() -> None:
                try:
                    with http.stream(
                        'POST',
                        '/api/v1/messages',
                        headers={
                            **JSON_HEADERS,
                            'X-CSRF-Token': csrf,
                            'Idempotency-Key': 'shutdown-test-001',
                        },
                        json={'content': 'What does the kit include?', 'locale': 'en'},
                    ) as response:
                        assert response.status_code == 200
                        for chunk in response.iter_text():
                            chunks.append(chunk)
                            if 'run.started' in ''.join(chunks):
                                started.set()
                except httpx.TransportError:
                    # A transport torn down by SIGTERM cannot promise a terminal frame.
                    pass

            thread = threading.Thread(target=consume)
            thread.start()
            assert started.wait(5)
            _stop(process)
            thread.join(5)
            assert not thread.is_alive()
            events = parse_sse(''.join(chunks))
            assert events[0]['type'] == 'run.started'
            assert not any(event['type'] == 'message.completed' for event in events)
            with closing(sqlite3.connect(database)) as connection:
                assert connection.execute('PRAGMA quick_check').fetchone()[0] == 'ok'
                assert connection.execute('SELECT state FROM runs').fetchone()[0] == 'cancelled'
                ledger = connection.execute(
                    'SELECT status,actual_micro,reserved_micro FROM spend_ledger'
                ).fetchone()
                assert ledger[0] == 'unreported' and ledger[1] is None and ledger[2] > 0
                assert connection.execute('SELECT role FROM messages').fetchall() == [('user',)]
            process = _start(database, port, 0, tmp_path / 'server.log')
            restored = http.post('/api/v1/session', headers=JSON_HEADERS, json={})
            assert restored.status_code == 200
            assert [message['role'] for message in restored.json()['messages']] == ['user']
            # The cancelled idempotency key does not silently regenerate after restart.
            duplicate = http.post(
                '/api/v1/messages',
                headers={**JSON_HEADERS, 'X-CSRF-Token': csrf, 'Idempotency-Key': 'shutdown-test-001'},
                json={'content': 'What does the kit include?', 'locale': 'en'},
            )
            assert duplicate.status_code == 409
            assert duplicate.json()['error']['code'] == 'idempotency_conflict'
    finally:
        _stop(process)
        if thread is not None:
            thread.join(5)
