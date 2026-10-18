"""In-process HTTP boundary proofs, with fake repository and no sockets/SDK/PG."""

import hashlib
import json
from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.application.product_analytics import AnalyticsService, QuotaExceededError
from app.domain.product_analytics import Event, Selection
from app.presentation.product_analytics import ReportOut, build_router
from tests.test_product_analytics import NOW, Rows, event

TOKEN = 'synthetic-local-analytics-token-not-a-secret'
ORIGIN = 'http://localhost:3107'
HEADERS = {'Origin': ORIGIN, 'Content-Type': 'application/json'}
AUTH = {'Authorization': f'Bearer {TOKEN}'}
PATH = '/api/v1/analytics/events'
PRIVATE = '/internal/v1/ops/product-analytics'


class Clock:
    def now(self) -> datetime:
        return NOW


class Store(Rows):
    def __init__(self) -> None:
        super().__init__()
        self.seen: set[str] = set()
        self.calls = 0
        self.checks = 0
        self.available = True
        self.limit = False

    async def ready(self) -> bool:
        self.checks += 1
        return self.available

    async def ingest(self, value: Event, now: datetime) -> bool:
        self.calls += 1
        if self.limit:
            raise QuotaExceededError
        if value.digest in self.seen:
            return False
        self.seen.add(value.digest)
        return True


def client(
    store: Store, *, enabled: bool = True, token: bytes | None = hashlib.sha256(TOKEN.encode()).digest()
) -> TestClient:
    app = FastAPI()
    app.include_router(
        build_router(
            AnalyticsService(store, synthetic=True),
            enabled=enabled,
            token_digest=token,
            origins=(ORIGIN,),
            clock=Clock(),
        )
    )
    return TestClient(app)


def test_disabled_channel_does_no_read_write_and_does_not_extend_chat_openapi() -> None:
    store = Store()
    with client(store, enabled=False) as http:
        assert http.post(PATH, json=event(), headers=HEADERS).status_code == 404
        assert http.get(PRIVATE, headers=AUTH).status_code == 404
        assert http.get('/openapi.json').json()['paths'] == {}
    assert store.calls == 0 and store.checks == 0


def test_accepted_and_duplicate_delivery_return_204_without_cookie() -> None:
    store = Store()
    value = event()
    with client(store) as http:
        first = http.post(PATH, json=value, headers=HEADERS)
        second = http.post(PATH, json=value, headers=HEADERS)
    assert first.status_code == second.status_code == 204
    assert 'set-cookie' not in first.headers
    assert first.headers['cache-control'] == 'no-store'
    assert len(store.seen) == 1
    assert str(value['event_id']) not in store.seen


@pytest.mark.parametrize(
    'headers',
    [
        {},
        {'Origin': 'https://unapproved.invalid'},
        {'Origin': ORIGIN, 'Cookie': 'synthetic=x'},
        {'Origin': ORIGIN, 'Authorization': 'Bearer synthetic'},
        [('Origin', ORIGIN), ('Origin', ORIGIN)],
    ],
)
def test_no_credential_association_or_unapproved_origin(headers: object) -> None:
    store = Store()
    with client(store) as http:
        assert http.post(PATH, json=event(), headers=headers).status_code == 403  # type: ignore[arg-type]
    assert store.calls == store.checks == 0


@pytest.mark.parametrize(
    ('body', 'content_type', 'status'),
    [
        (b'{}', 'text/plain', 415),
        (b'{' + b' ' * 1024 + b'}', 'application/json', 413),
        (b'{"event_name":"a","event_name":"b"}', 'application/json', 422),
        (b'\xff', 'application/json', 422),
        (b'[]', 'application/json', 422),
        (b'{"email":"private-synthetic@example.invalid"}', 'application/json', 422),
    ],
)
def test_input_limits_and_errors_never_echo_payload(body: bytes, content_type: str, status: int) -> None:
    store = Store()
    with client(store) as http:
        response = http.post(PATH, content=body, headers={'Origin': ORIGIN, 'Content-Type': content_type})
    assert response.status_code == status
    assert response.content == b'' and store.calls == 0


def test_actual_chunked_body_guard_ignores_lying_declared_length() -> None:
    store = Store()
    with client(store) as http:
        response = http.post(
            PATH,
            content=iter([b'{' + b' ' * 600, b' ' * 600 + b'}']),
            headers={**HEADERS, 'Content-Length': '1'},
        )
    assert response.status_code == 413 and store.calls == 0


def test_quota_and_schema_failure_are_closed_without_payload() -> None:
    store = Store()
    with client(store) as http:
        store.limit = True
        assert http.post(PATH, json=event(), headers=HEADERS).status_code == 429
        store.available = False
        assert http.post(PATH, json=event(), headers=HEADERS).status_code == 503
        assert http.get(PRIVATE, headers=AUTH).status_code == 503


@pytest.mark.parametrize(
    'suffix',
    [
        '?offset=3',
        '?offset=01',
        '?offset=1&offset=1',
        '?country=ES',
        '?route=/grafismo-fonetico/&section_id=leer',
        '?locale=en',
        '?period=year',
        '?session_id=synthetic',
    ],
)
def test_private_query_is_closed_before_storage(suffix: str) -> None:
    store = Store()
    with client(store) as http:
        assert http.get(PRIVATE + suffix, headers=AUTH).status_code == 422
    assert store.selections == [] and store.checks == 0


def test_private_bearer_and_uniform_selection_without_browser_secret_export() -> None:
    store = Store()
    with client(store) as http:
        assert http.get(PRIVATE).status_code == 401
        assert http.get(PRIVATE, headers={'Authorization': 'Bearer wrong'}).status_code == 401
        response = http.get(PRIVATE + '?route=/&section_id=hero&viewport_bucket=tablet', headers=AUTH)
        output = ReportOut.model_validate(response.json())
    assert output.synthetic is True and output.grid.available is True
    assert store.selections == [Selection(route='/', section_id='hero', viewport_bucket='tablet')]
    assert TOKEN not in response.text and response.headers['cache-control'] == 'no-store'


def test_runtime_report_matches_frozen_schema_example_vocabulary() -> None:
    from contracts.product_analytics import artifacts

    value = json.loads(artifacts()['examples/product-analytics.json'])
    assert value['fixture'] is True
    ReportOut.model_validate(value['report'])


def test_missing_token_hides_private_route_and_upstream_failure_is_not_bad_input() -> None:
    from app.application.product_analytics import Bucket

    store = Store()
    with client(store, token=None) as http:
        assert http.get(PRIVATE, headers=AUTH).status_code == 404
    # A corrupt repository result is a dependency failure, not a visitor validation error.
    store.value = (Bucket(NOW, 'unrecognized', 0, 0, 1, NOW, NOW),)
    with client(store) as http:
        response = http.get(PRIVATE, headers=AUTH)
    assert response.status_code == 503 and response.content == b''


def test_default_real_composition_hides_channel_without_extra_schema_or_io() -> None:
    from app.bootstrap.config import Settings
    from app.bootstrap.container import create_app

    app = create_app(
        Settings(
            _env_file=None,
            environment='test',
            ai_provider='fixture',
            allow_paid_ai=False,
            openai_api_key=None,
            allowed_origins=[ORIGIN],
        )
    )
    # No lifespan/socket/database or provider call is needed to establish the OFF routing contract.
    http = TestClient(app)
    assert http.post(PATH, headers=HEADERS, json=event()).status_code == 404
    assert http.get(PRIVATE, headers=AUTH).status_code == 404
    assert PATH not in app.openapi()['paths'] and PRIVATE not in app.openapi()['paths']


def test_request_deadline_covers_repository_wait_without_automatic_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio

    original_timeout = asyncio.timeout
    monkeypatch.setattr(
        'app.presentation.product_analytics.asyncio.timeout', lambda _: original_timeout(0.005)
    )

    class Blocked(Store):
        async def ready(self) -> bool:
            await asyncio.Event().wait()
            return True

    store = Blocked()
    with client(store) as http:
        assert http.post(PATH, headers=HEADERS, json=event()).status_code == 408
        assert http.get(PRIVATE, headers=AUTH).status_code == 503
    assert store.calls == 0


def test_oversized_single_chunk_is_rejected_before_copying_into_buffer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from typing import Any

    import app.presentation.product_analytics as boundary

    oversized_copies: list[int] = []

    class ObservedBuffer(bytearray):
        def extend(self, value: Any) -> None:
            if len(self) + len(value) > 1024:
                oversized_copies.append(len(self) + len(value))
            super().extend(value)

    monkeypatch.setattr(boundary, 'bytearray', ObservedBuffer, raising=False)
    store = Store()
    with client(store) as http:
        response = http.post(PATH, content=b'{' + b' ' * 1048576, headers=HEADERS)
    assert response.status_code == 413 and store.calls == 0
    assert oversized_copies == []


async def _composed_request(
    monkeypatch: pytest.MonkeyPatch, *, enabled: bool, mode: str, path: str = PATH, method: str = 'POST'
) -> tuple[int, int, list[int]]:
    import asyncio
    from types import SimpleNamespace

    import app.presentation.product_analytics as boundary
    from app.adapters.catalog_schema import CatalogParser
    from app.bootstrap import container
    from app.bootstrap.config import Settings

    settings = Settings(
        _env_file=None,
        environment='test',
        ai_provider='fixture',
        allow_paid_ai=False,
        openai_api_key=None,
        allowed_origins=[ORIGIN],
        application_storage='postgres',
        knowledge_backend='graphrag',
        postgres_private_dsn='postgresql://synthetic:synthetic@127.0.0.1:1/unused',
        postgres_knowledge_dsn='postgresql://synthetic:synthetic@127.0.0.1:1/unused',
        neo4j_uri='bolt://127.0.0.1:1',
        neo4j_password='synthetic-unused',
        product_analytics_enabled=enabled,
        max_body_bytes=2048,
    )
    persistence = container.build_persistence(
        settings, CatalogParser(frozenset(settings.catalog_allowed_hosts))
    )
    monkeypatch.setattr(container, 'build_persistence', lambda *_: persistence)
    app = container.create_app(settings, clock=Clock())
    calls = 0
    copied_after_receive: list[int] = []
    messages: list[dict[str, object]] = []
    timeout = asyncio.timeout
    monkeypatch.setattr(boundary, 'asyncio', SimpleNamespace(timeout=lambda _: timeout(0.005)))

    class ObservedBuffer(bytearray):
        def extend(self, value: bytes) -> None:
            copied_after_receive.append(calls)
            super().extend(value)

    monkeypatch.setattr(boundary, 'bytearray', ObservedBuffer, raising=False)
    request_headers = [(key.lower().encode(), value.encode()) for key, value in HEADERS.items()]
    if mode == 'cookie':
        request_headers.append((b'cookie', b'synthetic=not-associated'))
    scope = {
        'type': 'http',
        'asgi': {'version': '3.0'},
        'http_version': '1.1',
        'method': method,
        'scheme': 'http',
        'path': path,
        'raw_path': path.encode(),
        'query_string': b'',
        'root_path': '',
        'headers': request_headers,
        'server': ('localhost', 8000),
        'client': ('127.0.0.1', 1234),
    }

    async def receive() -> dict[str, object]:
        nonlocal calls
        calls += 1
        if mode == 'slow':
            await asyncio.Event().wait()
        size = 600 if mode == 'chunked' else 4096
        return {'type': 'http.request', 'body': b' ' * size, 'more_body': mode == 'chunked' and calls < 3}

    async def send(message: dict[str, object]) -> None:
        messages.append(message)

    try:
        await asyncio.wait_for(app(scope, receive, send), timeout=0.1)  # type: ignore[arg-type]
    finally:
        # Constructors only; no lifespan, connection, socket, service or SDK request was started.
        for resource in reversed(persistence.resources):
            await resource.close()
    status = next(int(message['status']) for message in messages if message['type'] == 'http.response.start')
    return status, calls, copied_after_receive


@pytest.mark.parametrize(('enabled', 'mode', 'status'), [(False, 'unused', 404), (True, 'cookie', 403)])
def test_real_composition_early_rejection_never_reads_body(
    monkeypatch: pytest.MonkeyPatch, enabled: bool, mode: str, status: int
) -> None:
    import asyncio

    actual, receives, _ = asyncio.run(_composed_request(monkeypatch, enabled=enabled, mode=mode))
    assert actual == status and receives == 0


def test_real_composition_streams_chunks_before_join_and_stops_at_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio

    status, receives, copied = asyncio.run(_composed_request(monkeypatch, enabled=True, mode='chunked'))
    assert status == 413 and receives == 2 and copied == [1]


def test_real_composition_deadline_covers_initial_slow_receive(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    status, receives, _ = asyncio.run(_composed_request(monkeypatch, enabled=True, mode='slow'))
    assert status == 408 and receives == 1


@pytest.mark.parametrize(
    ('method', 'path'), [('POST', '/api/v1/session'), ('PUT', PATH), ('POST', PATH + '/sibling')]
)
def test_other_unsafe_paths_keep_existing_global_limit(
    monkeypatch: pytest.MonkeyPatch, method: str, path: str
) -> None:
    import asyncio

    status, receives, copied = asyncio.run(
        _composed_request(monkeypatch, enabled=True, mode='oversized', path=path, method=method)
    )
    assert status == 422 and receives == 1 and copied == []
