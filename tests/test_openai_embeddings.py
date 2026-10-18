"""Actual SDK against local intercepted HTTP; no provider network or real credentials."""

import asyncio
import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from openai import AsyncOpenAI

from app.adapters.providers.openai_embeddings import FixtureHashEmbeddings, OpenAIEmbeddings
from app.domain.errors import RejectedError
from app.domain.knowledge import EmbeddingPurpose


class Accounting:
    def __init__(self) -> None:
        self.events: list[tuple[str, object]] = []
        self.refuse = False

    async def reserve(self, max_input_tokens: int, purpose: EmbeddingPurpose) -> str:
        self.events.append(('reserve', (max_input_tokens, purpose)))
        if self.refuse:
            raise ValueError('budget exhausted')
        return 'embedding:fixture'

    async def settle(self, operation_id: str, input_tokens: int) -> None:
        self.events.append(('settle', input_tokens))

    async def mark_unreported(self, operation_id: str) -> None:
        self.events.append(('unreported', operation_id))


def payload(count: int = 1) -> dict[str, Any]:
    return {
        'object': 'list',
        'model': 'text-embedding-3-small',
        'data': [
            {'object': 'embedding', 'index': i, 'embedding': [1.0] + [0.0] * 1535} for i in range(count)
        ],
        'usage': {'prompt_tokens': 2, 'total_tokens': 2},
    }


def test_real_sdk_request_identity_accounting_order_and_borrowed_client() -> None:
    async def run() -> None:
        accounting = Accounting()
        requests: list[dict[str, Any]] = []

        def handle(request: httpx.Request) -> httpx.Response:
            assert request.url.path == '/v1/embeddings'
            assert accounting.events[0] == ('reserve', (12, EmbeddingPurpose.INDEX))
            requests.append(json.loads(request.content))
            response = payload(2)
            response['data'].reverse()
            return httpx.Response(200, json=response)

        async with AsyncOpenAI(
            api_key='fixture-not-a-real-key',
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle)),
        ) as client:
            adapter = OpenAIEmbeddings(client, accounting)
            vectors = await adapter.encode(('hola', 'adiós!!'), EmbeddingPurpose.INDEX)
            assert len(vectors) == 2 and all(len(v) == 1536 for v in vectors)
            assert not client.is_closed()
        assert requests == [
            {
                'input': ['hola', 'adiós!!'],
                'model': 'text-embedding-3-small',
                'dimensions': 1536,
                'encoding_format': 'float',
            }
        ]
        assert accounting.events[-1] == ('settle', 2)

    asyncio.run(run())


@pytest.mark.parametrize('status', [429, 500, 503])
def test_provider_failure_never_retries_and_preserves_unknown_cost(status: int) -> None:
    async def run() -> None:
        accounting = Accounting()
        calls = 0

        def handle(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(status, json={'error': {'message': 'synthetic failure'}})

        async with AsyncOpenAI(
            api_key='fixture-not-a-real-key',
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle)),
        ) as client:
            with pytest.raises(RejectedError):
                await OpenAIEmbeddings(client, accounting).encode(('sample',), EmbeddingPurpose.QUERY)
        assert calls == 1
        assert [e[0] for e in accounting.events] == ['reserve', 'unreported']

    asyncio.run(run())


@pytest.mark.parametrize(
    'mutate',
    [
        lambda p: p.update(model='other-model'),
        lambda p: p.update(data=[]),
        lambda p: p['data'][0].update(index=3),
        lambda p: p['data'][0].update(embedding=[0.0] * 1536),
        lambda p: p['data'][0].update(embedding=[1.0] * 64),
    ],
)
def test_malformed_vector_response_keeps_reported_usage(mutate: Callable[[dict[str, Any]], None]) -> None:
    async def run() -> None:
        accounting = Accounting()
        data = payload()
        mutate(data)
        async with AsyncOpenAI(
            api_key='fixture-not-a-real-key',
            http_client=httpx.AsyncClient(
                transport=httpx.MockTransport(lambda _: httpx.Response(200, json=data))
            ),
        ) as client:
            with pytest.raises(RejectedError):
                await OpenAIEmbeddings(client, accounting).encode(('sample',), EmbeddingPurpose.QUERY)
        assert ('settle', 2) in accounting.events
        # Real accounting's mark_unreported is idempotent and cannot erase settled usage.
        assert accounting.events[-1][0] == 'unreported'

    asyncio.run(run())


def test_missing_usage_conservatively_remains_unreported() -> None:
    async def run() -> None:
        accounting = Accounting()
        data = payload()
        data.pop('usage')
        async with AsyncOpenAI(
            api_key='fixture-not-a-real-key',
            http_client=httpx.AsyncClient(
                transport=httpx.MockTransport(lambda _: httpx.Response(200, json=data))
            ),
        ) as client:
            with pytest.raises(RejectedError):
                await OpenAIEmbeddings(client, accounting).encode(('sample',), EmbeddingPurpose.QUERY)
        assert [e[0] for e in accounting.events] == ['reserve', 'unreported']

    asyncio.run(run())


def test_cancellation_after_http_attempt_preserves_reservation() -> None:
    async def run() -> None:
        entered = asyncio.Event()
        accounting = Accounting()

        async def handle(request: httpx.Request) -> httpx.Response:
            entered.set()
            await asyncio.Event().wait()
            raise AssertionError('unreachable')

        async with AsyncOpenAI(
            api_key='fixture-not-a-real-key',
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle)),
        ) as client:
            task = asyncio.create_task(
                OpenAIEmbeddings(client, accounting).encode(('sample',), EmbeddingPurpose.QUERY)
            )
            await asyncio.wait_for(entered.wait(), 2)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        assert [e[0] for e in accounting.events] == ['reserve', 'unreported']

    asyncio.run(run())


def test_invalid_input_and_exhausted_budget_cannot_make_http_request() -> None:
    async def run() -> None:
        accounting = Accounting()

        def handle(request: httpx.Request) -> httpx.Response:
            raise AssertionError('no request authorized')

        async with AsyncOpenAI(
            api_key='fixture-not-a-real-key',
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle)),
        ) as client:
            adapter = OpenAIEmbeddings(client, accounting)
            for texts in [(), ('',), ('á' * 4001,), ('x',) * 33]:
                with pytest.raises(ValueError, match='embedding'):
                    await adapter.encode(texts, EmbeddingPurpose.INDEX)
            assert accounting.events == []
            accounting.refuse = True
            with pytest.raises(ValueError, match='budget exhausted'):
                await adapter.encode(('sample',), EmbeddingPurpose.QUERY)

    asyncio.run(run())


def test_fixture_is_deterministic_and_explicitly_not_semantic_identity() -> None:
    async def run() -> None:
        adapter = FixtureHashEmbeddings()
        assert adapter.spec.provider == 'fixture' and adapter.spec.dimensions == 64
        assert await adapter.encode(('Hola mundo',), EmbeddingPurpose.INDEX) == await adapter.encode(
            ('Hola mundo',), EmbeddingPurpose.QUERY
        )

    asyncio.run(run())
