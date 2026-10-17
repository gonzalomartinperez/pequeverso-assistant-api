"""Real loopback HTTP/SSE + PostgreSQL/Neo4j; scripted generation, no provider SDK.

Explicit isolated fixture configuration is required. This is protocol/persistence evidence,
not a real-model quality evaluation, TLS validation, production deployment or VPS benchmark.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import secrets
import socket
import stat
import threading
import time
from collections.abc import Awaitable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any, TypeVar
from urllib.parse import urlsplit

import httpx
import pytest
import uvicorn

from app.adapters.catalog.knowledge import PARSER_VERSION, build_public_corpus
from app.adapters.catalog_schema import CatalogParser
from app.adapters.neo4j.database import Neo4jDatabase
from app.adapters.neo4j.public_graph import Neo4jPublicGraph
from app.adapters.openai_embeddings import FixtureHashEmbeddings
from app.adapters.postgres.database import PostgresDatabase
from app.adapters.postgres.knowledge import PostgresKnowledgeStore
from app.adapters.postgres.private_ledger import PostgresLedger
from app.application.indexing import KnowledgeIndexer
from app.bootstrap.config import DEFAULT_CATALOG, Settings
from app.bootstrap.container import create_app
from tests.support import JSON_HEADERS, FixedClock, ScriptedProvider, answer_json, mutation_headers, parse_sse

CONFIG = os.environ.get('PV_GRAPH_HTTP_FIXTURE_CONFIG', '')
pytestmark = pytest.mark.skipif(not CONFIG, reason='explicit isolated PG+Neo fixture configuration required')
T = TypeVar('T')


@dataclass(frozen=True)
class Fixture:
    values: dict[str, Any] = field(repr=False)
    body: bytes = field(repr=False)
    clock: FixedClock = field(repr=False)

    def settings(self) -> Settings:
        return Settings(
            _env_file=None,
            environment='test',
            ai_provider='fixture',
            allow_paid_ai=False,
            openai_api_key=None,
            assistant_enabled=True,
            official_help_enabled=False,
            catalog_url=None,
            catalog_file=DEFAULT_CATALOG,
            catalog_allowed_hosts=['pequeverso.com', 'consumer.hotmart.com', 'refund.hotmart.com'],
            observability_enabled=False,
            telemetry_otlp_endpoint=None,
            application_storage='postgres',
            knowledge_backend='graphrag',
            postgres_private_dsn=self.values['postgres_private_dsn'],
            postgres_knowledge_dsn=self.values['postgres_knowledge_dsn'],
            neo4j_uri=self.values['neo4j_uri'],
            neo4j_username=self.values['neo4j_username'],
            neo4j_password=self.values['neo4j_password'],
            session_cookie_secure=False,
            allowed_origins=['http://localhost:3000'],
            monthly_budget_usd='10',
            daily_budget_usd='1',
            messages_per_client_per_hour=100,
            messages_per_session_per_day=100,
        )


def _load_fixture() -> Fixture:
    path = Path(CONFIG)
    if path.is_symlink() or not path.is_file() or stat.S_IMODE(path.stat().st_mode) != 0o600:
        raise ValueError('fixture configuration must be an ordinary private0600 file')
    if path.stat().st_uid != os.getuid() or path.stat().st_size > 32768:
        raise ValueError('fixture configuration ownership or size is invalid')
    values = json.loads(path.read_text())
    if (
        values.get('isolated_fixture') is not True
        or values.get('runtime_roles_verified_non_owner') is not True
    ):
        raise ValueError('isolated nonowner fixture identities must be explicitly verified')
    locations = [
        urlsplit(values[key])
        for key in ('postgres_admin_dsn', 'postgres_private_dsn', 'postgres_knowledge_dsn')
    ]
    if any(
        p.scheme != 'postgresql'
        or p.hostname != '127.0.0.1'
        or p.port != 55440
        or not p.path.startswith('/pv_')
        for p in locations
    ):
        raise ValueError('HTTP fixture is restricted to its dedicated PostgreSQL loopback database')
    if len({p.path for p in locations}) != 1 or len({p.username for p in locations}) != 3:
        raise ValueError('fixture requires distinct private/public/admin identities in one database')
    if values['neo4j_uri'] != 'bolt://127.0.0.1:17689':
        raise ValueError('HTTP fixture requires its dedicated loopback graph')
    body = DEFAULT_CATALOG.read_bytes()
    parser = CatalogParser(frozenset({'pequeverso.com', 'consumer.hotmart.com', 'refund.hotmart.com'}))
    catalog = parser(body)
    return Fixture(values, body, FixedClock(catalog.generated_at + timedelta(hours=1)))


async def _index(fixture: Fixture) -> None:
    settings = fixture.settings()
    parser = CatalogParser(frozenset(settings.catalog_allowed_hosts))
    embeddings = FixtureHashEmbeddings()
    corpus = build_public_corpus(fixture.body, fixture.clock.now(), embeddings.spec, parser)
    database = PostgresDatabase(fixture.values['postgres_admin_dsn'])
    public = PostgresDatabase(fixture.values['postgres_indexer_dsn'])
    accounting = PostgresDatabase(fixture.values['postgres_embedding_dsn'])
    graph_database = Neo4jDatabase(
        fixture.values['neo4j_uri'], fixture.values['neo4j_username'], fixture.values['neo4j_password']
    )
    try:
        await database.open()
        await database.migrate()  # Explicit fixture preparation, never application startup.
        await public.open()
        await accounting.open()
        await graph_database.open()
        store = PostgresKnowledgeStore(public, parser, embeddings.spec, PARSER_VERSION)
        indexer = KnowledgeIndexer(
            store,
            Neo4jPublicGraph(graph_database.driver),
            embeddings,
            PostgresLedger(accounting).abandon_index_pending,
        )
        indexed = await indexer.index(corpus)
        assert indexed.version == corpus.revision.version
    finally:
        await graph_database.close()
        await accounting.close()
        await public.close()
        await database.close()


@pytest.fixture(scope='module')
def real_fixture() -> Fixture:
    fixture = _load_fixture()
    asyncio.run(_index(fixture))
    return fixture


@dataclass
class Running:
    url: str
    app: Any = field(repr=False)
    loop: asyncio.AbstractEventLoop = field(repr=False)

    def await_(self, work: Awaitable[T]) -> T:
        async def resolve() -> T:
            return await work

        return asyncio.run_coroutine_threadsafe(resolve(), self.loop).result(8)


class StartupRefusedError(RuntimeError):
    pass


def capture(name: str, payload: object) -> None:
    directory = os.environ.get('PV_GRAPH_HTTP_ARTIFACT_DIR')
    if directory:
        descriptor = os.open(Path(directory) / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, 'w') as target:
            json.dump(payload, target, ensure_ascii=False, indent=2)


@contextmanager
def serve(fixture: Fixture, provider: ScriptedProvider) -> Iterator[Running]:
    app = create_app(fixture.settings(), provider=provider, clock=fixture.clock)
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(app, host='127.0.0.1', port=port, log_config=None, lifespan='on', access_log=False)
    )
    loops: list[asyncio.AbstractEventLoop] = []
    failures: list[str] = []

    async def run() -> None:
        loops.append(asyncio.get_running_loop())
        await server.serve()

    def target() -> None:
        try:
            asyncio.run(run())
        except SystemExit:
            # Uvicorn exits3 when a second instance's lifespan refuses ownership.
            failures.append('SystemExit')
        except Exception as error:  # noqa: BLE001 - record only safe thread failure classes
            failures.append(type(error).__name__)  # Never expose credentials/SQL/exception text.

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 15
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.02)
        if not server.started or failures or not loops:
            raise StartupRefusedError('isolated graph application did not acquire healthy startup')
        yield Running(f'http://127.0.0.1:{port}', app, loops[0])
    finally:
        server.should_exit = True
        thread.join(12)
        assert not thread.is_alive(), 'fixture server failed to drain and close'


def open_session(client: httpx.Client) -> tuple[str, list[dict[str, Any]]]:
    response = client.post('/api/v1/session', headers=JSON_HEADERS, json={})
    assert response.status_code in (200, 201)
    payload = response.json()
    return payload['csrf_token'], payload['messages']


def ask(client: httpx.Client, csrf: str, key: str) -> tuple[int, list[dict[str, Any]]]:
    response = client.post(
        '/api/v1/messages',
        headers=mutation_headers(csrf, key),
        json={'content': '¿Qué incluye Grafismo Fonético?', 'response_language': 'es'},
    )
    assert response.headers.get('content-type', '').startswith('text/event-stream')
    return response.status_code, parse_sse(response.text)


def test_real_graph_http_security_idempotency_isolation_and_restart_history(real_fixture: Fixture) -> None:
    provider = ScriptedProvider(
        output=answer_json(
            'Puedes consultar el material publicado.',
            references=[{'kind': 'product', 'id': 'grafismo-fonetico'}],
        )
    )
    cookie: dict[str, str] = {}
    saved: list[dict[str, Any]] = []
    key = f'graph-http-{secrets.token_hex(8)}'
    with (
        serve(real_fixture, provider) as live,
        httpx.Client(base_url=live.url, timeout=15) as first,
        httpx.Client(base_url=live.url, timeout=15) as other,
    ):
        assert first.get('/health/ready').status_code == 200
        csrf, initial = open_session(first)
        assert initial == []
        cookie = dict(first.cookies)
        session_response = first.post('/api/v1/session', headers=JSON_HEADERS, json={})
        emitted = session_response.headers['set-cookie'].lower()
        assert 'httponly' in emitted and 'samesite=lax' in emitted
        assert 'secure' not in emitted  # Local HTTP only; production TLS cookies are a separate gate.
        foreign_csrf, foreign_history = open_session(other)
        assert foreign_history == []
        denied = first.post('/api/v1/messages', headers=JSON_HEADERS, json={'content': 'Hola'})
        assert denied.status_code == 403
        denied = first.post(
            '/api/v1/messages',
            headers={**mutation_headers(csrf), 'Origin': 'https://untrusted.invalid'},
            json={'content': 'Hola'},
        )
        assert denied.status_code == 403 and provider.calls == []
        status, events = ask(first, csrf, key)
        capture('completed-sse.json', events)
        assert status == 200 and events[-1]['type'] == 'run.completed'
        completed = next(event['message'] for event in events if event['type'] == 'message.completed')
        assert completed['products'][0]['id'] == 'grafismo-fonetico'
        assert len(provider.calls) == provider.closed == 1
        passages = next(
            item.text for item in provider.calls[0].inputs if item.text.startswith('retrieved_public_data:\n')
        )
        retrieved = json.loads(passages.split('\n', 1)[1])
        capture(
            'retrieved-provenance.json',
            {
                'version': retrieved['version'],
                'catalog_sha256': retrieved['catalog_sha256'],
                'passages': [{'id': item['id'], 'sha256': item['sha256']} for item in retrieved['passages']],
            },
        )
        assert retrieved['catalog_sha256'] == hashlib.sha256(real_fixture.body).hexdigest()
        assert retrieved['passages'] and all(
            hashlib.sha256(p['text'].encode()).hexdigest() == p['sha256'] for p in retrieved['passages']
        )
        replay_status, replay = ask(first, csrf, key)
        assert (
            replay_status == 200
            and next(e['message'] for e in replay if e['type'] == 'message.completed') == completed
        )
        assert len(provider.calls) == 1
        conflict = first.post(
            '/api/v1/messages', headers=mutation_headers(csrf, key), json={'content': 'Otra consulta'}
        )
        assert conflict.status_code == 409
        _, saved = open_session(first)
        assert len(saved) == 2 and saved[-1] == completed
        assert open_session(other)[1] == []
        assert foreign_csrf != csrf
    fresh_provider = ScriptedProvider()
    with (
        serve(real_fixture, fresh_provider) as live,
        httpx.Client(base_url=live.url, cookies=cookie, timeout=15) as restored,
    ):
        csrf, messages = open_session(restored)
        assert messages == saved and fresh_provider.calls == []
        assert ask(restored, csrf, key)[0] == 200 and fresh_provider.calls == []
        deleted = restored.delete('/api/v1/session', headers=mutation_headers(csrf))
        assert deleted.status_code == 204
        assert open_session(restored)[1] == []


def test_real_graph_cancel_after_delta_keeps_unknown_spend_and_blocks_overlapping_owner(
    real_fixture: Fixture,
) -> None:
    provider = ScriptedProvider(
        output=answer_json('Puedo ayudarte a explorar el material publicado. ' * 12),
        usage=None,
        hang=True,
        delay=0.002,
    )
    key = f'graph-cancel-{secrets.token_hex(8)}'
    ready = threading.Event()
    chunks: list[str] = []
    run_ids: list[str] = []
    errors: list[str] = []
    cookie: dict[str, str] = {}
    spent_after = (0, 0)
    month, day = real_fixture.clock.now().strftime('%Y-%m'), real_fixture.clock.now().strftime('%Y-%m-%d')
    with serve(real_fixture, provider) as live, httpx.Client(base_url=live.url, timeout=15) as client:
        csrf, _ = open_session(client)
        cookie = dict(client.cookies)
        ledger = live.app.state.services.chat.ledger
        spent_before = live.await_(ledger.spent(month, day))

        def consume() -> None:
            try:
                with (
                    httpx.Client(base_url=live.url, cookies=cookie, timeout=15) as stream_client,
                    stream_client.stream(
                        'POST',
                        '/api/v1/messages',
                        headers=mutation_headers(csrf, key),
                        json={'content': '¿Qué incluye Grafismo Fonético?', 'response_language': 'es'},
                    ) as response,
                ):
                    assert response.status_code == 200
                    run_ids.append(response.headers['x-run-id'])
                    for line in response.iter_lines():
                        chunks.append(line + '\n')
                        if line == 'event: message.delta':
                            ready.set()
            except Exception as error:  # noqa: BLE001 - record only safe thread failure classes
                errors.append(type(error).__name__)
                ready.set()

        thread = threading.Thread(target=consume)
        thread.start()
        try:
            assert ready.wait(10) and not errors and len(run_ids) == 1
            overlapping = ScriptedProvider()
            with pytest.raises(StartupRefusedError), serve(real_fixture, overlapping):
                raise AssertionError('overlapping runtime must not start or recover the live owner')
            assert overlapping.calls == [] and client.get('/health/ready').status_code == 200
            cancelled = client.post(
                f'/api/v1/runs/{run_ids[0]}/cancel', headers=mutation_headers(csrf), json={}
            )
            assert cancelled.status_code == 202
            thread.join(10)
            assert not thread.is_alive() and errors == []
            events = parse_sse(''.join(chunks))
            assert any(event['type'] == 'message.delta' for event in events)
            assert events[-1]['type'] == 'run.cancelled'
            assert not any(event['type'] == 'message.completed' for event in events)
            assert len(provider.calls) == provider.closed == 1
            _, history = open_session(client)
            assert [message['role'] for message in history] == ['user']
            spent_after = live.await_(ledger.spent(month, day))
            assert spent_after[0] > spent_before[0] and spent_after[1] > spent_before[1]
        finally:
            if thread.is_alive() and run_ids:
                client.post(f'/api/v1/runs/{run_ids[0]}/cancel', headers=mutation_headers(csrf), json={})
                thread.join(10)
            capture('cancelled-sse.json', ''.join(chunks))
    fresh_provider = ScriptedProvider()
    with (
        serve(real_fixture, fresh_provider) as live,
        httpx.Client(base_url=live.url, cookies=cookie, timeout=15) as restored,
    ):
        _, history = open_session(restored)
        assert [message['role'] for message in history] == ['user']
        assert fresh_provider.calls == []
        assert live.await_(live.app.state.services.chat.ledger.spent(month, day)) == spent_after
