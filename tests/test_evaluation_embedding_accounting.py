"""Disposable ledgers and real SDK MockTransport only; never read provider credentials."""

import asyncio
import json
from pathlib import Path
from typing import Any

import httpx2
import pytest
from openai import AsyncOpenAI

from app.adapters.providers.openai_embeddings import OpenAIEmbeddings
from app.domain.errors import RejectedError
from app.domain.knowledge import EmbeddingPurpose
from scripts.real_eval_budget import Envelope, EvaluationEmbeddingAccounting


class ApplicationAccounting:
    def __init__(self) -> None:
        self.events: list[tuple[str, object]] = []
        self.pending: set[str] = set()
        self.known: dict[str, int] = {}
        self.refuse = False

    async def reserve(self, max_input_tokens: int, purpose: EmbeddingPurpose) -> str:
        self.events.append(('reserve', (max_input_tokens, purpose)))
        if self.refuse:
            raise ValueError('synthetic application budget exhausted')
        operation = f'embedding:{purpose.value}:{len(self.events)}'
        self.pending.add(operation)
        return operation

    async def settle(self, operation_id: str, input_tokens: int) -> None:
        assert operation_id not in self.known
        self.pending.discard(operation_id)
        self.known[operation_id] = input_tokens
        self.events.append(('settle', input_tokens))

    async def mark_unreported(self, operation_id: str) -> None:
        self.events.append(('unreported', operation_id))


def response_payload() -> dict[str, Any]:
    return {
        'object': 'list',
        'model': 'text-embedding-3-small',
        'data': [{'object': 'embedding', 'index': 0, 'embedding': [1.0] + [0.0] * 1535}],
        'usage': {'prompt_tokens': 2, 'total_tokens': 2},
    }


@pytest.mark.parametrize('purpose', [EmbeddingPurpose.QUERY, EmbeddingPurpose.INDEX])
def test_real_sdk_reserves_both_ledgers_before_io_and_settles_once(
    tmp_path: Path, purpose: EmbeddingPurpose
) -> None:
    async def run() -> None:
        app = ApplicationAccounting()
        envelope = Envelope(tmp_path / 'evaluation.sqlite3', max_attempts=650)
        accounting = EvaluationEmbeddingAccounting(app, envelope)
        requests = []

        def handle(request: httpx2.Request) -> httpx2.Response:
            assert envelope.snapshot() == {'attempts': 1, 'reserved_micro_usd': 11000, 'stop_reason': None}
            assert app.events == [('reserve', (4, purpose))]
            assert len(app.pending) == 1
            requests.append(json.loads(request.content))
            return httpx2.Response(200, json=response_payload())

        async with AsyncOpenAI(
            api_key='synthetic-not-a-real-key',
            max_retries=0,
            http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handle), trust_env=False),
        ) as client:
            assert len(await OpenAIEmbeddings(client, accounting).encode(('hola',), purpose)) == 1
        assert len(requests) == 1
        assert requests[0]['model'] == 'text-embedding-3-small'
        assert app.events[-1] == ('settle', 2)
        assert not app.pending and len(app.known) == 1
        assert envelope.snapshot() == {'attempts': 1, 'reserved_micro_usd': 1, 'stop_reason': None}
        assert Envelope(envelope.path, max_attempts=650).snapshot() == envelope.snapshot()

    asyncio.run(run())


@pytest.mark.parametrize('reason', ['money', 'attempts', 'existing_stop'])
def test_outer_refusal_records_application_known_zero_and_never_dispatches(
    tmp_path: Path, reason: str
) -> None:
    async def run() -> None:
        envelope = Envelope(tmp_path / 'evaluation.sqlite3', cap_micro=11000, max_attempts=1)
        if reason == 'money':
            envelope.reserve()
        elif reason == 'attempts':
            envelope.settle(envelope.reserve(), 0, 0)
        else:
            envelope.stop('AuthenticationError')
        before = envelope.snapshot()
        app = ApplicationAccounting()
        calls = 0

        def handle(_: httpx2.Request) -> httpx2.Response:
            nonlocal calls
            calls += 1
            raise AssertionError('budget refusal must occur before SDK dispatch')

        async with AsyncOpenAI(
            api_key='synthetic-not-a-real-key',
            http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handle), trust_env=False),
        ) as client:
            with pytest.raises(RejectedError):
                await OpenAIEmbeddings(client, EvaluationEmbeddingAccounting(app, envelope)).encode(
                    ('hola',), EmbeddingPurpose.QUERY
                )
        assert calls == 0
        assert app.events[-1] == ('settle', 0) and not app.pending
        assert envelope.snapshot()['attempts'] == before['attempts']
        assert envelope.snapshot()['reserved_micro_usd'] == before['reserved_micro_usd']
        assert envelope.snapshot()['stop_reason']

    asyncio.run(run())


def test_application_refusal_does_not_allocate_private_attempt(tmp_path: Path) -> None:
    async def run() -> None:
        envelope = Envelope(tmp_path / 'evaluation.sqlite3')
        app = ApplicationAccounting()
        app.refuse = True
        with pytest.raises(ValueError, match='application budget'):
            await EvaluationEmbeddingAccounting(app, envelope).reserve(4, EmbeddingPurpose.INDEX)
        assert envelope.snapshot()['attempts'] == 0

    asyncio.run(run())


@pytest.mark.parametrize('mode', ['http_failure', 'missing_usage', 'cancel'])
def test_unknown_sdk_cost_retains_both_reservations_and_stops_without_retry(
    tmp_path: Path, mode: str
) -> None:
    async def run() -> None:
        app = ApplicationAccounting()
        envelope = Envelope(tmp_path / 'evaluation.sqlite3')
        calls = 0

        def handle(_: httpx2.Request) -> httpx2.Response:
            nonlocal calls
            calls += 1
            if mode == 'cancel':
                raise asyncio.CancelledError
            if mode == 'http_failure':
                return httpx2.Response(503, json={'error': {'message': 'synthetic failure'}})
            payload = response_payload()
            payload.pop('usage')
            return httpx2.Response(200, json=payload)

        async with AsyncOpenAI(
            api_key='synthetic-not-a-real-key',
            http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handle), trust_env=False),
        ) as client:
            adapter = OpenAIEmbeddings(client, EvaluationEmbeddingAccounting(app, envelope))
            if mode == 'cancel':
                with pytest.raises(asyncio.CancelledError):
                    await adapter.encode(('hola',), EmbeddingPurpose.QUERY)
            else:
                with pytest.raises(RejectedError):
                    await adapter.encode(('hola',), EmbeddingPurpose.QUERY)
        assert calls == 1 and len(app.pending) == 1 and not app.known
        assert [event[0] for event in app.events] == ['reserve', 'unreported']
        assert envelope.snapshot() == {
            'attempts': 1,
            'reserved_micro_usd': 11000,
            'stop_reason': 'missing_embedding_usage',
        }
        with pytest.raises(RejectedError):
            envelope.reserve()

    asyncio.run(run())


def test_known_usage_malformed_vector_is_not_refunded_or_settled_twice(tmp_path: Path) -> None:
    async def run() -> None:
        app = ApplicationAccounting()
        envelope = Envelope(tmp_path / 'evaluation.sqlite3')
        payload = response_payload()
        payload['data'][0]['embedding'] = [0.0] * 1536
        async with AsyncOpenAI(
            api_key='synthetic-not-a-real-key',
            http_client=httpx2.AsyncClient(
                transport=httpx2.MockTransport(lambda _: httpx2.Response(200, json=payload)), trust_env=False
            ),
        ) as client:
            with pytest.raises(RejectedError):
                await OpenAIEmbeddings(client, EvaluationEmbeddingAccounting(app, envelope)).encode(
                    ('hola',), EmbeddingPurpose.QUERY
                )
        assert [event[0] for event in app.events] == ['reserve', 'settle']
        assert app.known and not app.pending
        assert envelope.snapshot() == {'attempts': 1, 'reserved_micro_usd': 1, 'stop_reason': None}

    asyncio.run(run())


@pytest.mark.parametrize(('tokens', 'bound'), [(True, 4), (-1, 4), (5, 4), (1, 0), (1, 240001), (1, True)])
def test_invalid_embedding_usage_keeps_full_reservation(tmp_path: Path, tokens: int, bound: int) -> None:
    envelope = Envelope(tmp_path / 'evaluation.sqlite3')
    attempt = envelope.reserve()
    assert not envelope.settle_embedding(attempt, tokens, input_byte_bound=bound)
    assert envelope.snapshot() == {
        'attempts': 1,
        'reserved_micro_usd': 11000,
        'stop_reason': 'embedding_usage_exceeds_bound',
    }


def test_duplicate_embedding_usage_stops_without_refund_or_second_application_settlement(
    tmp_path: Path,
) -> None:
    async def run() -> None:
        app = ApplicationAccounting()
        envelope = Envelope(tmp_path / 'evaluation.sqlite3')
        accounting = EvaluationEmbeddingAccounting(app, envelope)
        operation = await accounting.reserve(4000, EmbeddingPurpose.INDEX)
        await accounting.settle(operation, 4000)
        assert envelope.snapshot()['reserved_micro_usd'] == 176
        with pytest.raises(ValueError, match='already settled'):
            await accounting.settle(operation, 0)
        assert envelope.snapshot()['reserved_micro_usd'] == 176
        assert envelope.snapshot()['stop_reason'] == 'duplicate_usage'
        assert [e[0] for e in app.events] == ['reserve', 'settle']
        await accounting.mark_unreported(operation)
        assert envelope.snapshot()['reserved_micro_usd'] == 176

    asyncio.run(run())


def test_generation_rates_schema_and_shared_attempt_count_are_unchanged(tmp_path: Path) -> None:
    envelope = Envelope(tmp_path / 'evaluation.sqlite3', max_attempts=650)
    with envelope.connect() as db:
        before = db.execute("SELECT sql FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
    envelope.settle(envelope.reserve(), 5000, 1000)
    assert envelope.snapshot()['reserved_micro_usd'] == 2475
    assert envelope.settle_embedding(envelope.reserve(), 240000, input_byte_bound=240000)
    assert envelope.snapshot()['attempts'] == 2
    assert envelope.snapshot()['reserved_micro_usd'] == 2475 + 10560
    with envelope.connect() as db:
        assert (
            db.execute("SELECT sql FROM sqlite_master WHERE type='table' ORDER BY name").fetchall() == before
        )
    with pytest.raises(ValueError, match='attempt limit cannot be changed'):
        Envelope(envelope.path, max_attempts=649)


def test_late_known_usage_preserves_original_unknown_stop(tmp_path: Path) -> None:
    async def run() -> None:
        app = ApplicationAccounting()
        envelope = Envelope(tmp_path / 'evaluation.sqlite3')
        accounting = EvaluationEmbeddingAccounting(app, envelope)
        operation = await accounting.reserve(4, EmbeddingPurpose.QUERY)
        await accounting.mark_unreported(operation)
        await accounting.mark_unreported(operation)
        await accounting.settle(operation, 2)
        assert envelope.snapshot()['reserved_micro_usd'] == 1
        assert envelope.snapshot()['stop_reason'] == 'missing_embedding_usage'
        assert [e[0] for e in app.events] == ['reserve', 'unreported', 'settle']

    asyncio.run(run())
