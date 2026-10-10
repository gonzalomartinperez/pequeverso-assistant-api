"""No network and no real key: verify the independent evaluation envelope."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx2 as httpx
import pytest

from app.ai.provider import ModelInput, ModelRequest
from app.domain.errors import RejectedError
from scripts.real_eval_budget import BoundedProvider, Envelope


def test_envelope_is_atomic_persistent_and_never_refunds(tmp_path: Path) -> None:
    path = tmp_path / 'budget.sqlite3'
    envelope = Envelope(path)

    def attempt(_: int) -> bool:
        try:
            envelope.reserve()
            return True
        except RejectedError:
            return False

    with ThreadPoolExecutor(max_workers=16) as pool:
        accepted = list(pool.map(attempt, range(500)))
    assert sum(accepted) == 90
    assert Envelope(path).snapshot() == {
        'attempts': 90,
        'reserved_micro_usd': 990000,
        'stop_reason': 'budget_or_attempt_limit',
    }
    with pytest.raises(RejectedError):
        Envelope(path).reserve()


def test_stopped_envelope_rejects_after_reopen(tmp_path: Path) -> None:
    path = tmp_path / 'budget.sqlite3'
    envelope = Envelope(path)
    envelope.reserve()
    envelope.stop('AuthenticationError')
    with pytest.raises(RejectedError):
        Envelope(path).reserve()
    assert Envelope(path).snapshot()['reserved_micro_usd'] == 11000


def test_auth_failure_is_one_request_and_unknown_usage_stays_reserved(tmp_path: Path) -> None:
    requests: list[dict[str, object]] = []

    def failure(request: httpx.Request) -> httpx.Response:
        import json

        assert str(request.url) == 'https://api.openai.com/v1/responses'
        requests.append(json.loads(request.content))
        return httpx.Response(401, json={'error': {'message': 'synthetic', 'type': 'invalid_request_error'}})

    envelope = Envelope(tmp_path / 'budget.sqlite3')
    provider = BoundedProvider('synthetic-key', envelope, transport=httpx.MockTransport(failure))
    request = ModelRequest(
        'hello', (ModelInput('user', 'fixture'),), {'type': 'object'}, 4000, 'opaque', 'catalog'
    )

    async def run() -> None:
        with pytest.raises(RejectedError):
            async for _ in provider.stream(request):
                pass
        with pytest.raises(RejectedError):
            async for _ in provider.stream(request):
                pass

    asyncio.run(run())
    assert len(requests) == 1
    assert requests[0]['model'] == 'gpt-6-luna'
    assert requests[0]['reasoning'] == {'effort': 'medium'}
    assert requests[0]['service_tier'] == 'default'
    assert requests[0]['store'] is False
    assert requests[0]['max_output_tokens'] == 4000
    assert envelope.snapshot() == {
        'attempts': 1,
        'reserved_micro_usd': 11000,
        'stop_reason': 'AuthenticationError',
    }


def test_oversize_request_never_dispatches(tmp_path: Path) -> None:
    envelope = Envelope(tmp_path / 'budget.sqlite3')
    provider = BoundedProvider('synthetic-key', envelope)
    request = ModelRequest('x' * 24000, (), {}, 4000, 'opaque', 'catalog')

    async def run() -> None:
        with pytest.raises(RejectedError):
            async for _ in provider.stream(request):
                pass

    asyncio.run(run())
    assert envelope.snapshot()['attempts'] == 0
    assert envelope.snapshot()['stop_reason'] == 'request_bound'


def test_known_usage_settles_conservatively_and_unknown_does_not(tmp_path: Path) -> None:
    envelope = Envelope(tmp_path / 'budget.sqlite3')
    attempt = envelope.reserve()
    envelope.settle(attempt, 5000, 1000)
    envelope.reserve()  # unknown usage retains 11000
    assert envelope.snapshot()['reserved_micro_usd'] == 13475
    envelope.settle(attempt, 24001, 1)
    assert envelope.snapshot()['stop_reason'] == 'usage_exceeds_bound'


def test_attempt_limit_remains_after_known_zero_usage(tmp_path: Path) -> None:
    envelope = Envelope(tmp_path / 'budget.sqlite3')
    for _ in range(400):
        envelope.settle(envelope.reserve(), 0, 0)
    with pytest.raises(RejectedError):
        envelope.reserve()
    assert envelope.snapshot()['attempts'] == 400


def test_cap_cannot_change_on_reopen(tmp_path: Path) -> None:
    path = tmp_path / 'budget.sqlite3'
    Envelope(path, 250000)
    with pytest.raises(ValueError, match='cannot be changed'):
        Envelope(path, 1000000)


def test_provider_error_never_logs_synthetic_secret(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    sentinel = 'sk-proj-SECRET-SENTINEL-never-print-987654321'

    def failure(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={'error': {'message': sentinel, 'type': 'invalid_request_error'}})

    envelope = Envelope(tmp_path / 'budget.sqlite3')
    provider = BoundedProvider(sentinel, envelope, transport=httpx.MockTransport(failure))
    request = ModelRequest('hello', (), {'type': 'object'}, 4000, 'opaque', 'catalog')

    async def run() -> None:
        with pytest.raises(RejectedError):
            async for _ in provider.stream(request):
                pass

    asyncio.run(run())
    assert sentinel not in caplog.text
    assert 'sk-proj-SECRET' not in caplog.text
    assert sentinel not in str(envelope.snapshot())
    assert sentinel not in str(provider.receipts)
    assert envelope.snapshot()['stop_reason'] == 'NotFoundError'


def test_duplicate_usage_cannot_reduce_accounted_spend(tmp_path: Path) -> None:
    envelope = Envelope(tmp_path / 'budget.sqlite3')
    attempt = envelope.reserve()
    envelope.settle(attempt, 5000, 1000)
    envelope.settle(attempt, 0, 0)
    assert envelope.snapshot()['reserved_micro_usd'] == 2475
    assert envelope.snapshot()['stop_reason'] == 'duplicate_usage'


@pytest.mark.parametrize(('inputs', 'outputs'), [(-1, 1), (1, 4001), (True, 1)])
def test_invalid_usage_retains_reservation_and_halts(tmp_path: Path, inputs: int, outputs: int) -> None:
    envelope = Envelope(tmp_path / 'budget.sqlite3')
    attempt = envelope.reserve()
    envelope.settle(attempt, inputs, outputs)
    assert envelope.snapshot()['reserved_micro_usd'] == 11000
    assert envelope.snapshot()['stop_reason'] == 'usage_exceeds_bound'


def test_aggregate_cap_survives_clock_database_resets(tmp_path: Path) -> None:
    import json

    from app.bootstrap.config import Settings
    from scripts import evaluate_corpus as corpus

    calls = []

    def success_without_usage(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        answer = json.dumps(
            {
                'answer': 'Puedes consultar la información en la página del producto.',
                'references': [],
                'sources': [],
                'follow_ups': [],
            }
        )
        events = [
            {'type': 'response.output_text.delta', 'delta': answer},
            {
                'type': 'response.completed',
                'response': {
                    'id': 'resp-synthetic',
                    'object': 'response',
                    'created_at': 0,
                    'status': 'completed',
                    'model': 'gpt-6-luna',
                    'output': [],
                },
            },
        ]
        body = ''.join(f'data: {json.dumps(event)}\n\n' for event in events)
        return httpx.Response(200, headers={'content-type': 'text/event-stream'}, content=body)

    envelope = Envelope(tmp_path / 'budget.sqlite3', 12000)
    provider = BoundedProvider(
        'synthetic-key', envelope, transport=httpx.MockTransport(success_without_usage)
    )
    sample = corpus.load()[0]
    cases = [
        dict(sample, id='offset-current', clock_offset_days=0),
        dict(sample, id='offset-future', clock_offset_days=20),
    ]
    rows = corpus.run_pipeline(Settings(_env_file=None, environment='test'), cases, provider=provider)
    assert len(calls) == 1
    assert len(rows) == 2
    assert envelope.snapshot()['reserved_micro_usd'] == 11000
    assert envelope.snapshot()['stop_reason'] == 'budget_or_attempt_limit'
    assert rows[1]['gates']


def test_default_conversation_cli_ignores_ambient_paid_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.bootstrap import container
    from scripts import evaluate_conversations as conv
    from scripts import evaluate_corpus as corpus

    monkeypatch.setenv('AI_PROVIDER', 'openai')
    monkeypatch.setenv('ALLOW_PAID_AI', 'true')
    monkeypatch.setenv('OPENAI_API_KEY', 'synthetic-env-sentinel')
    monkeypatch.setattr('sys.argv', ['evaluate_conversations.py'])
    calls = []

    def forbidden(**kwargs: object) -> object:
        calls.append(True)
        raise AssertionError('fixture CLI must never build a paid provider')

    monkeypatch.setattr(container, 'AsyncOpenAI', forbidden)
    assert conv.main() == 0
    settings = corpus.settings_for_eval()
    assert settings.ai_provider == 'fixture' and settings.allow_paid_ai is False
    assert settings.openai_api_key is None
    assert calls == []


def test_default_local_server_ignores_ambient_paid_configuration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi.testclient import TestClient

    from app.bootstrap import container
    from scripts import serve_bounded_real_eval as server

    monkeypatch.setenv('AI_PROVIDER', 'openai')
    monkeypatch.setenv('ALLOW_PAID_AI', 'true')
    monkeypatch.setenv('OPENAI_API_KEY', 'synthetic-env-sentinel')
    monkeypatch.setattr('sys.argv', ['serve_bounded_real_eval.py', '--state-dir', str(tmp_path)])
    calls = []

    def forbidden(**kwargs: object) -> object:
        calls.append(True)
        raise AssertionError('fixture server must never build a paid provider')

    def run(app: object, **kwargs: object) -> None:
        assert kwargs['host'] == '127.0.0.1'
        with TestClient(app) as c:
            csrf = c.post(
                '/api/v1/session',
                headers={'Origin': 'http://localhost:3342', 'Content-Type': 'application/json'},
                json={},
            ).json()['csrf_token']
            result = c.post(
                '/api/v1/messages',
                headers={
                    'Origin': 'http://localhost:3342',
                    'Content-Type': 'application/json',
                    'X-CSRF-Token': csrf,
                    'Idempotency-Key': 'server-fixture01',
                },
                json={'content': '¿Qué incluye el kit?'},
            )
            assert result.status_code == 200 and 'run.completed' in result.text

    monkeypatch.setattr(container, 'AsyncOpenAI', forbidden)
    monkeypatch.setattr(server.uvicorn, 'run', run)
    server.main()
    assert calls == []
    assert (tmp_path / 'local-ops.env.local').read_text().splitlines()[0] == (
        'LIVE_OPS_URL=http://localhost:18088'
    )
