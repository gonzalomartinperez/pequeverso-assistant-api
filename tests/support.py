"""Shared test helpers: a controllable clock, scripted providers and an SSE reader."""

from __future__ import annotations

import asyncio
import json
import secrets
from collections.abc import AsyncGenerator, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from app.ai.provider import ModelChunk, ModelRequest, TextChunk, UsageChunk
from app.bootstrap.config import DEFAULT_CATALOG, Settings
from app.bootstrap.container import create_app
from app.domain.budget import Usage
from app.domain.errors import FailureCode, RejectedError

ORIGIN = 'http://localhost:3000'
JSON_HEADERS = {'Origin': ORIGIN, 'Content-Type': 'application/json'}
CATALOG_BYTES = DEFAULT_CATALOG.read_bytes()


class FixedClock:
    def __init__(self, now: datetime | None = None) -> None:
        self.current = now or datetime(2026, 9, 28, 12, 0, tzinfo=UTC)

    def now(self) -> datetime:
        return self.current

    def advance(self, **kwargs: float) -> None:
        self.current += timedelta(**kwargs)


def answer_json(
    answer: str,
    references: list[dict[str, str]] | None = None,
    sources: list[str] | None = None,
    follow_ups: list[str] | None = None,
) -> str:
    return json.dumps(
        {
            'answer': answer,
            'references': references or [],
            'sources': sources or [],
            'follow_ups': follow_ups or [],
        },
        ensure_ascii=False,
    )


@dataclass
class ScriptedProvider:
    """Streams a fixed structured output; optionally fails, hangs or delays between chunks."""

    output: str = field(default_factory=lambda: answer_json('Hola, soy el asistente de Pequeverso.'))
    usage: Usage | None = field(default_factory=lambda: Usage(input_tokens=5000, output_tokens=200))
    fail_with: FailureCode | None = None
    hang: bool = False
    delay: float = 0.0
    chunk: int = 7
    calls: list[ModelRequest] = field(default_factory=list)
    closed: int = 0

    @property
    def model(self) -> str:
        return 'scripted'

    async def stream(self, request: ModelRequest) -> AsyncGenerator[ModelChunk]:
        self.calls.append(request)
        try:
            if self.fail_with is not None:
                raise RejectedError(self.fail_with)
            for start in range(0, len(self.output), self.chunk):
                if self.delay:
                    await asyncio.sleep(self.delay)
                yield TextChunk(self.output[start : start + self.chunk])
            if self.hang:
                await asyncio.Event().wait()
            if self.usage is not None:
                yield UsageChunk(self.usage)
        finally:
            self.closed += 1


def settings(tmp_path: Path, **overrides: Any) -> Settings:
    values: dict[str, Any] = {'database_path': str(tmp_path / 'test.sqlite3'), 'environment': 'test'}
    values.update(overrides)
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


@contextmanager
def client(
    tmp_path: Path, provider: Any = None, clock: FixedClock | None = None, **overrides: Any
) -> Iterator[TestClient]:
    app = create_app(settings(tmp_path, **overrides), provider=provider, clock=clock or FixedClock())
    with TestClient(app, base_url='http://localhost:8000') as test_client:
        yield test_client


def open_session(c: TestClient) -> str:
    response = c.post('/api/v1/session', headers=JSON_HEADERS, json={})
    assert response.status_code in (200, 201), response.text
    token: str = response.json()['csrf_token']
    return token


def mutation_headers(csrf: str, key: str | None = None) -> dict[str, str]:
    return {**JSON_HEADERS, 'X-CSRF-Token': csrf, 'Idempotency-Key': key or secrets.token_hex(8)}


def parse_sse(body: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for block in body.split('\n\n'):
        lines = [line for line in block.split('\n') if line and not line.startswith(':')]
        if not lines:
            continue
        fields = dict(line.split(': ', 1) for line in lines)
        data = json.loads(fields['data'])
        assert data['type'] == fields['event']
        assert str(data['sequence']) == fields['id']
        events.append(data)
    return events


def ask(
    c: TestClient, csrf: str, content: str, key: str | None = None, page: str | None = None
) -> tuple[int, list[dict[str, Any]], Any]:
    body: dict[str, Any] = {'content': content}
    if page:
        body['page'] = page
    with c.stream('POST', '/api/v1/messages', headers=mutation_headers(csrf, key), json=body) as response:
        text = ''.join(response.iter_text())
    if response.headers.get('content-type', '').startswith('text/event-stream'):
        return response.status_code, parse_sse(text), None
    return response.status_code, [], json.loads(text)


@contextmanager
def live_server(
    tmp_path: Path, provider: Any = None, clock: FixedClock | None = None, **overrides: Any
) -> Iterator[str]:
    """Serve the app with uvicorn on a real socket (disconnects and streaming behave as in production)."""
    import socket
    import threading
    import time

    import uvicorn

    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
    app = create_app(settings(tmp_path, **overrides), provider=provider, clock=clock or FixedClock())
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port, log_config=None, lifespan='on'))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.02)
    try:
        yield f'http://127.0.0.1:{port}'
    finally:
        server.should_exit = True
        thread.join(10)
