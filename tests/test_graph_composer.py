"""Finite real LangGraph runtime, local providers and no tracing/network calls."""

from __future__ import annotations

import asyncio
import hashlib
import json
import socket
import sqlite3
import threading
from contextlib import closing
from datetime import timedelta
from pathlib import Path

import httpx
import pytest

from app.adapters.catalog_schema import CatalogParser
from app.adapters.graph.composer import GraphAnswerComposer, GraphPrepared
from app.ai.composer import ComposerSettings, GroundedComposer
from app.application.ports import DeltaEvent, DraftEvent, GenerationError, Turn
from app.bootstrap import container
from app.domain.catalog import ActiveCatalog, PriceStatus
from app.domain.errors import FailureCode, RejectedError
from app.domain.knowledge import (
    ChunkKind,
    EmbeddingSpec,
    KnowledgeChunk,
    KnowledgeRevision,
    RetrievalStrategy,
    RetrievedKnowledge,
)
from app.domain.language import Language
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

CATALOG = CatalogParser(frozenset({'pequeverso.com', 'consumer.hotmart.com', 'refund.hotmart.com'}))(
    CATALOG_BYTES
)
ACTIVE = ActiveCatalog(
    CATALOG, hashlib.sha256(CATALOG_BYTES).hexdigest(), CATALOG.generated_at, timedelta(hours=168)
)


def _knowledge(active: ActiveCatalog) -> RetrievedKnowledge:
    document = active.catalog.documents[0]
    text = f'{document.title}\n{document.text}'
    chunk = KnowledgeChunk(
        f'document:{document.id}',
        ChunkKind.DOCUMENT,
        document.id,
        document.title,
        text,
        'https://pequeverso.com/soporte/',
        document.product_ids,
        hashlib.sha256(text.encode()).hexdigest(),
        '/documents/0',
    )
    revision = KnowledgeRevision(
        'b' * 64, active.sha256, 'c' * 40, 'test-v1', EmbeddingSpec('fixture', 'hash64-v1', 64)
    )
    return RetrievedKnowledge(revision, (chunk,), (RetrievalStrategy.LEXICAL,))


class Retrieval:
    def __init__(self, *, failure: bool = False, wait: bool = False) -> None:
        self.calls = 0
        self.closed = 0
        self.failure = failure
        self.wait = wait
        self.started = asyncio.Event()

    async def ready(self, active: ActiveCatalog) -> bool:
        return True

    async def retrieve(
        self, active: ActiveCatalog, question: str, product_ids: tuple[str, ...], language: Language
    ) -> RetrievedKnowledge:
        self.calls += 1
        self.started.set()
        try:
            if self.wait:
                await asyncio.Event().wait()
            if self.failure:
                raise RejectedError(FailureCode.DEPENDENCY_UNAVAILABLE)
            return _knowledge(active)
        finally:
            self.closed += 1


def _composer(provider: ScriptedProvider, retrieval: Retrieval) -> GraphAnswerComposer:
    return GraphAnswerComposer(GroundedComposer(provider, ComposerSettings(4000, 40000)), retrieval, 24000)


def _turn() -> Turn:
    return Turn(ACTIVE, PriceStatus.VERIFIED, (), '¿Qué incluye el kit?', 'home', 'synthetic')


def test_prepare_never_retrieves_or_dispatches_and_reserves_a_fixed_input_bound() -> None:
    retrieval = Retrieval()
    provider = ScriptedProvider()
    prepared = _composer(provider, retrieval).prepare(_turn())
    assert isinstance(prepared, GraphPrepared)
    assert prepared.input_size_bytes == 24000
    assert not prepared.generation_started and not prepared.catalog_source_ids
    assert retrieval.calls == 0 and provider.calls == []


def test_graph_streams_once_and_records_exact_sent_passage_hashes() -> None:
    async def scenario() -> None:
        retrieval = Retrieval()
        provider = ScriptedProvider()
        composer = _composer(provider, retrieval)
        prepared = composer.prepare(_turn())
        events = [event async for event in composer.compose(prepared)]
        assert isinstance(prepared, GraphPrepared)
        assert any(isinstance(event, DeltaEvent) for event in events)
        assert sum(isinstance(event, DraftEvent) for event in events) == 1
        assert retrieval.calls == 1 and len(provider.calls) == provider.closed == 1
        assert prepared.generation_started and prepared.retrieval is not None
        request = provider.calls[0]
        assert request.size_bytes() <= prepared.input_size_bytes == 24000
        evidence = json.loads(
            next(
                item.text.split('\n', 1)[1]
                for item in request.inputs
                if item.text.startswith('retrieved_public_data:')
            )
        )
        assert evidence['catalog_sha256'] == ACTIVE.sha256
        assert tuple(item['id'] for item in evidence['passages']) == prepared.sent_chunk_ids
        for item in evidence['passages']:
            assert hashlib.sha256(item['text'].encode()).hexdigest() == item['sha256']

    asyncio.run(scenario())


def test_local_retrieval_error_does_not_dispatch_or_retry_generation() -> None:
    async def scenario() -> None:
        retrieval = Retrieval(failure=True)
        provider = ScriptedProvider()
        composer = _composer(provider, retrieval)
        prepared = composer.prepare(_turn())
        with pytest.raises(GenerationError) as error:
            _ = [event async for event in composer.compose(prepared)]
        assert error.value.code is FailureCode.DEPENDENCY_UNAVAILABLE
        assert error.value.usage is not None and error.value.usage.input_tokens == 0
        assert provider.calls == [] and retrieval.calls == 1
        assert isinstance(prepared, GraphPrepared) and not prepared.generation_started

    asyncio.run(scenario())


def test_cancellation_closes_retrieval_without_starting_generation() -> None:
    async def scenario() -> None:
        retrieval = Retrieval(wait=True)
        provider = ScriptedProvider()
        composer = _composer(provider, retrieval)
        prepared = composer.prepare(_turn())
        stream = composer.compose(prepared)
        task = asyncio.create_task(anext(stream))
        await retrieval.started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await stream.aclose()
        assert retrieval.calls == retrieval.closed == 1 and provider.calls == []
        assert isinstance(prepared, GraphPrepared) and not prepared.generation_started

    asyncio.run(scenario())


def test_ambient_tracing_is_disabled_for_entire_graph_lifetime(monkeypatch: pytest.MonkeyPatch) -> None:
    attempted: list[object] = []

    def forbidden_connect(*args: object, **kwargs: object) -> None:
        attempted.append(args)
        raise AssertionError('runtime tracing must not attempt network access')

    monkeypatch.setenv('LANGSMITH_TRACING', 'true')
    monkeypatch.setenv('LANGCHAIN_TRACING_V2', 'true')
    monkeypatch.setenv('LANGSMITH_API_KEY', 'synthetic-not-a-secret')
    monkeypatch.setenv('LANGSMITH_ENDPOINT', 'https://192.0.2.1')
    monkeypatch.setattr(socket.socket, 'connect', forbidden_connect)

    async def scenario() -> None:
        provider = ScriptedProvider()
        composer = _composer(provider, Retrieval())
        _ = [event async for event in composer.compose(composer.prepare(_turn()))]
        await asyncio.sleep(0.01)
        assert len(provider.calls) == 1

    asyncio.run(scenario())
    assert attempted == []


def test_http_sse_persistence_and_idempotency_use_real_graph(tmp_path: Path) -> None:
    provider = ScriptedProvider(output=answer_json('Hola, puedo ayudarte a elegir.'))
    retrieval = Retrieval()
    with client(tmp_path, provider=provider) as http:
        http.app.state.services.chat.composer = _composer(provider, retrieval)
        session = open_session(http)
        status, events, _ = ask(http, session, '¿Qué incluye el kit?', key='graph-once')
        assert status == 200 and events[-2]['type'] == 'message.completed'
        history = http.post('/api/v1/session', headers=JSON_HEADERS, json={})
        assert history.status_code == 200
        assert 'Hola, puedo ayudarte a elegir.' in history.text
        repeated, _, _ = ask(http, session, '¿Qué incluye el kit?', key='graph-once')
        assert repeated == 200
        assert retrieval.calls == len(provider.calls) == 1


def test_http_local_failure_reports_no_generation_and_keeps_history(tmp_path: Path) -> None:
    provider = ScriptedProvider()
    retrieval = Retrieval(failure=True)
    with client(tmp_path, provider=provider) as http:
        http.app.state.services.chat.composer = _composer(provider, retrieval)
        session = open_session(http)
        status, events, _ = ask(http, session, '¿Qué incluye el kit?')
        # Existing v1 SSE deliberately maps internal dependency failures to its safe code.
        assert status == 200 and events[-1]['code'] == 'generation_failed'
        assert len(provider.calls) == 0 and retrieval.calls == 1
        history = http.post('/api/v1/session', headers=JSON_HEADERS, json={})
        assert history.status_code == 200 and '¿Qué incluye el kit?' in history.text


def test_closing_graph_after_first_delta_closes_provider_exactly_once() -> None:
    async def scenario() -> None:
        provider = ScriptedProvider(hang=True, usage=None, delay=0.002)
        composer = _composer(provider, Retrieval())
        prepared = composer.prepare(_turn())
        stream = composer.compose(prepared)
        event = await anext(stream)
        assert isinstance(event, DeltaEvent)
        await stream.aclose()
        assert len(provider.calls) == provider.closed == 1
        assert isinstance(prepared, GraphPrepared) and prepared.generation_started

    asyncio.run(scenario())


def test_real_http_cancel_after_delta_retains_unknown_spend_and_no_partial_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = ScriptedProvider(
        output=answer_json('Puedo ayudarte a elegir. ' * 12), hang=True, usage=None, delay=0.002
    )
    retrieval = Retrieval()

    def composer_factory(model, settings):
        return GraphAnswerComposer(GroundedComposer(model, settings), retrieval, 24000)

    monkeypatch.setattr(container, 'GroundedComposer', composer_factory)
    with live_server(tmp_path, provider) as url, httpx.Client(base_url=url, timeout=10) as http:
        csrf = http.post('/api/v1/session', headers=JSON_HEADERS, json={}).json()['csrf_token']
        first_delta = threading.Event()
        chunks: list[str] = []
        run_ids: list[str] = []
        errors: list[BaseException] = []

        def consume() -> None:
            try:
                with http.stream(
                    'POST',
                    '/api/v1/messages',
                    headers=mutation_headers(csrf, 'graph-cancel-after-delta'),
                    json={'content': '¿Qué incluye el kit?'},
                ) as response:
                    assert response.status_code == 200
                    run_ids.append(response.headers['X-Run-ID'])
                    for chunk in response.iter_text():
                        chunks.append(chunk)
                        if 'event: message.delta' in ''.join(chunks):
                            first_delta.set()
            except (AssertionError, httpx.HTTPError, KeyError, ValueError) as error:
                errors.append(error)
                first_delta.set()

        thread = threading.Thread(target=consume)
        thread.start()
        try:
            assert first_delta.wait(5) and not errors and len(run_ids) == 1
            cancelled = http.post(
                f'/api/v1/runs/{run_ids[0]}/cancel', headers=mutation_headers(csrf), json={}
            )
            assert cancelled.status_code == 202
            thread.join(5)
            assert not thread.is_alive() and not errors
            assert parse_sse(''.join(chunks))[-1]['type'] == 'run.cancelled'
            assert len(provider.calls) == provider.closed == retrieval.calls == 1
            restored = http.post('/api/v1/session', headers=JSON_HEADERS, json={}).json()
            assert [message['role'] for message in restored['messages']] == ['user']
            with closing(sqlite3.connect(tmp_path / 'test.sqlite3')) as db:
                row = db.execute('SELECT status,actual_micro,reserved_micro FROM spend_ledger').fetchone()
                assert row[0] == 'unreported' and row[1] is None and row[2] > 0
                assert db.execute('SELECT model_call FROM run_metrics').fetchone()[0] == 1
        finally:
            if thread.is_alive() and run_ids:
                http.post(f'/api/v1/runs/{run_ids[0]}/cancel', headers=mutation_headers(csrf), json={})
                thread.join(5)
