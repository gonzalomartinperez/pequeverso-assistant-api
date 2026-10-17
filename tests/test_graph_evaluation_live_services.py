"""Real PG/Neo/socket boundaries with intercepted SDK HTTP; ZERO provider network/paid use.

The OpenAI embedding vectors and generation are synthetic transport fixtures, not semantic
or model-quality evidence. Requires an explicitly isolated four-capability fixture config.
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import asdict
from datetime import timedelta
from pathlib import Path
from typing import Any

import httpx2
import pytest
from openai import DefaultAsyncHttpxClient
from pydantic import SecretStr

from app.adapters.catalog_schema import CatalogParser
from app.bootstrap.config import DEFAULT_CATALOG, Settings
from app.bootstrap.evaluation_index import (
    EvaluationIndexConfig,
    evaluation_spend_snapshot,
    index_evaluation_snapshot,
)
from app.domain.errors import RejectedError
from scripts import evaluate_graph_end_to_end as graph_runner
from scripts.evaluate_end_to_end import ORIGIN, evaluate
from scripts.real_eval_budget import BoundedProvider, Envelope
from tests.support import FixedClock

CONFIG = os.environ.get('PV_GRAPH_HTTP_FIXTURE_CONFIG', '')
pytestmark = pytest.mark.skipif(
    not CONFIG, reason='isolated Graph evaluation SDK-mock services not requested'
)


def configuration() -> tuple[dict[str, str], FixedClock, EvaluationIndexConfig]:
    values = graph_runner.graph_configuration(Path(CONFIG))
    parser = CatalogParser(frozenset({'pequeverso.com', 'consumer.hotmart.com', 'refund.hotmart.com'}))
    clock = FixedClock(parser(DEFAULT_CATALOG.read_bytes()).generated_at + timedelta(hours=1))
    index = EvaluationIndexConfig(
        SecretStr(values['postgres_indexer_dsn']),
        SecretStr(values['postgres_embedding_dsn']),
        values['neo4j_uri'],
        values['neo4j_username'],
        SecretStr(values['neo4j_password']),
    )
    return values, clock, index


def test_index_query_generation_share_envelope_through_real_http_and_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    values, clock, index = configuration()
    envelope = Envelope(tmp_path / 'synthetic-sdk-budget.sqlite3', max_attempts=650)
    wires: list[str] = []
    receipts: list[dict[str, Any]] = []
    retrievals: list[dict[str, Any]] = []

    def handle(request: httpx2.Request) -> httpx2.Response:
        payload = json.loads(request.content)
        assert request.url.host == 'api.openai.com'
        assert envelope.snapshot()['attempts'] == len(wires) + 1
        wires.append(request.url.path)
        if request.url.path == '/v1/embeddings':
            assert payload['model'] == 'text-embedding-3-small' and payload['dimensions'] == 1536
            assert (
                receipts[-1]['attempt'] == envelope.snapshot()['attempts'] and receipts[-1]['usage'] is None
            )
            return httpx2.Response(
                200,
                json={
                    'object': 'list',
                    'model': 'text-embedding-3-small',
                    'data': [
                        {'object': 'embedding', 'index': i, 'embedding': [1.0] + [0.0] * 1535}
                        for i in range(len(payload['input']))
                    ],
                    'usage': {'prompt_tokens': 2, 'total_tokens': 2},
                },
            )
        assert request.url.path == '/v1/responses'
        assert payload['model'] == 'gpt-6-luna' and payload['reasoning'] == {'effort': 'medium'}
        assert payload['service_tier'] == 'default' and payload['store'] is False
        assert any(item['content'].startswith('retrieved_public_data:\n') for item in payload['input'])
        answer = json.dumps(
            {
                'answer': 'Puedes consultar la información publicada en la página del producto.',
                'references': [{'kind': 'product', 'id': 'grafismo-fonetico'}],
                'sources': [],
                'follow_ups': [],
            }
        )
        events = [
            {'type': 'response.output_text.delta', 'delta': answer},
            {
                'type': 'response.completed',
                'response': {
                    'id': 'resp-synthetic-fixture',
                    'object': 'response',
                    'created_at': 0,
                    'status': 'completed',
                    'model': 'gpt-6-luna',
                    'output': [],
                    'usage': {'input_tokens': 500, 'output_tokens': 50, 'total_tokens': 550},
                },
            },
        ]
        return httpx2.Response(
            200,
            headers={'content-type': 'text/event-stream'},
            content=''.join('data: ' + json.dumps(event) + '\n\n' for event in events),
        )

    transport = httpx2.MockTransport(handle)
    monkeypatch.setattr(
        graph_runner,
        'provider_http_client',
        lambda: DefaultAsyncHttpxClient(
            transport=transport, verify=True, follow_redirects=False, trust_env=False
        ),
    )
    bounded = BoundedProvider('synthetic-sdk-mock-not-a-real-key', envelope, transport=transport)
    embedding_factory, runtime_factory = graph_runner.factories(bounded, receipts, retrievals)
    cold = asyncio.run(
        index_evaluation_snapshot(index, DEFAULT_CATALOG.read_bytes(), clock, embedding_factory)
    )
    reused = asyncio.run(
        index_evaluation_snapshot(index, DEFAULT_CATALOG.read_bytes(), clock, embedding_factory)
    )
    assert cold.reused_vectors is False and reused.reused_vectors is True
    assert asdict(cold.stamp) == asdict(reused.stamp)
    assert wires == ['/v1/embeddings', '/v1/embeddings']
    settings = Settings(
        _env_file=None,
        environment='test',
        ai_provider='openai',
        allow_paid_ai=True,
        openai_api_key=SecretStr('synthetic-sdk-mock-not-a-real-key'),
        application_storage='postgres',
        knowledge_backend='graphrag',
        postgres_private_dsn=SecretStr(values['postgres_private_dsn']),
        postgres_knowledge_dsn=SecretStr(values['postgres_knowledge_dsn']),
        neo4j_uri=values['neo4j_uri'],
        neo4j_username=values['neo4j_username'],
        neo4j_password=SecretStr(values['neo4j_password']),
        catalog_url=None,
        catalog_file=DEFAULT_CATALOG,
        allowed_origins=[ORIGIN],
        observability_enabled=False,
        official_help_enabled=False,
        assistant_enabled=True,
    )
    destination = tmp_path / 'sdk-mock-socket'
    destination.mkdir(mode=0o700)
    manifest = {
        'reply_policy': 'spanish_native',
        'policy_expected_languages': {'sdk-mock-turn:1': 'es'},
        'cases': [
            {
                'id': 'sdk-mock-turn',
                'family': 'contents',
                'locale': 'es',
                'turns': [{'question': '¿Qué incluye Grafismo Fonético?', 'expected_language': 'es'}],
            }
        ],
    }
    summary = evaluate(
        manifest,
        destination,
        'a' * 40,
        bounded=bounded,
        graph_settings=settings,
        graph_factory=runtime_factory,
        graph_spend=lambda: evaluation_spend_snapshot(
            SecretStr(values['postgres_private_dsn']), SecretStr(values['postgres_knowledge_dsn']), clock
        ),
        embedding_receipts=receipts,
        retrieval_receipts=retrievals,
    )
    assert summary['stop_reason'] is None and summary['queries'] == 1
    assert summary['history_mismatches'] == 0 and summary['structural_flagged_queries'] == 0
    assert summary['all_sdk_attempts'] == 4 and summary['embedding_sdk_attempts'] == 3
    assert wires == ['/v1/embeddings'] * 3 + ['/v1/responses']
    assert envelope.snapshot() == {'attempts': 4, 'reserved_micro_usd': 196, 'stop_reason': None}
    row = summary['cases'][0]
    assert row['replay_new_provider_calls'] == row['replay_new_embedding_calls'] == 0
    assert row['history_matches'] and row['replay_answer_matches'] and row['replay_history_unchanged']
    assert row['evidence'][0]['retrieved_public']['catalog_sha256'] == cold.stamp.catalog_sha256
    assert row['evidence'][0]['retrieved_public']['passages']
    assert len(row['retrieval']) == 1
    assert row['retrieval'][0]['catalog_only'] is False
    assert row['retrieval'][0]['sent_chunk_ids'] == [
        p['id'] for p in row['evidence'][0]['retrieved_public']['passages']
    ]
    assert row['replay_new_retrievals'] == 0
    assert summary['invalid_csrf_http_status'] == summary['invalid_origin_http_status'] == 403
    assert summary['isolated_visitor_empty_history'] is True


def test_cold_index_outer_cap_refusal_occurs_before_any_sdk_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    values, clock, index = configuration()
    envelope = Envelope(tmp_path / 'synthetic-exhausted-budget.sqlite3', cap_micro=11000, max_attempts=650)
    historical = envelope.reserve()
    # Exhaust the cap with KNOWN usage; an unknown historical reservation is a different admission gate.
    envelope.settle(historical, 24000, 4000)
    calls = []

    def handle(request: httpx2.Request) -> httpx2.Response:
        calls.append(request.url.path)
        raise AssertionError('exhausted independent envelope cannot dispatch even an index request')

    transport = httpx2.MockTransport(handle)
    monkeypatch.setattr(
        graph_runner,
        'provider_http_client',
        lambda: DefaultAsyncHttpxClient(
            transport=transport, verify=True, follow_redirects=False, trust_env=False
        ),
    )
    bounded = BoundedProvider('synthetic-sdk-mock-not-a-real-key', envelope, transport=transport)
    embedding_factory, _ = graph_runner.factories(bounded, [])
    # A distinct valid snapshot hash needs a cold index; never erase the previous prepared version.
    with pytest.raises(RejectedError):
        asyncio.run(
            index_evaluation_snapshot(index, DEFAULT_CATALOG.read_bytes() + b'\n', clock, embedding_factory)
        )
    assert calls == []
    assert envelope.snapshot() == {
        'attempts': 1,
        'reserved_micro_usd': 11000,
        'stop_reason': 'budget_or_attempt_limit',
    }
    totals = asyncio.run(
        evaluation_spend_snapshot(
            SecretStr(values['postgres_private_dsn']), SecretStr(values['postgres_knowledge_dsn']), clock
        )
    )
    assert all(row['pending'] == row['estimated'] == 0 for row in totals)
