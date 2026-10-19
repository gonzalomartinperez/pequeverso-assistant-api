"""No network and no real key: verify the independent evaluation envelope."""

from __future__ import annotations

import asyncio
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
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


def _acknowledge(envelope: Envelope, *, attempts: int = 1, reserved: int = 2475) -> None:
    envelope.acknowledge_fixed_case_gate(
        expected_attempts=attempts,
        expected_reserved_micro=reserved,
        source_revision='a' * 40,
        verification_sha256='b' * 64,
        manifest_sha256='c' * 64,
    )


def _original_ledger_rows(envelope: Envelope) -> tuple[list[tuple], ...]:
    with envelope.connect() as db:
        return (
            db.execute('SELECT * FROM attempts').fetchall(),
            db.execute('SELECT * FROM status').fetchall(),
            db.execute('SELECT * FROM limits').fetchall(),
            db.execute('SELECT * FROM attempt_limits').fetchall(),
        )


def test_explicit_gate_acknowledgment_preserves_all_original_accounting_and_stops(tmp_path: Path) -> None:
    path = tmp_path / 'budget.sqlite3'
    envelope = Envelope(path, max_attempts=650)
    envelope.settle(envelope.reserve(), 5000, 1000)
    envelope.stop('case_gate_failure')
    original = _original_ledger_rows(envelope)
    with pytest.raises(RejectedError):
        envelope.reserve()
    _acknowledge(envelope)
    assert _original_ledger_rows(envelope) == original
    with envelope.connect() as db:
        assert db.execute('SELECT count(*) FROM gate_resolutions').fetchone() == (1,)
    assert Envelope(path, max_attempts=650).snapshot() == {
        'attempts': 1,
        'reserved_micro_usd': 2475,
        'stop_reason': None,
    }
    with pytest.raises(ValueError, match='only a fixed case gate'):
        _acknowledge(envelope)
    assert envelope.reserve() == 2
    envelope.stop('case_gate_failure')  # A new failure is never implicitly acknowledged.
    with pytest.raises(RejectedError):
        envelope.reserve()
    with envelope.connect() as db:
        assert db.execute('SELECT reason FROM status').fetchall() == [
            ('case_gate_failure',),
            ('case_gate_failure',),
        ]


@pytest.mark.parametrize(
    'reason',
    [
        'AuthenticationError',
        'PermissionDeniedError',
        'missing_usage',
        'request_bound',
        'budget_or_attempt_limit',
    ],
)
def test_gate_acknowledgment_cannot_bypass_other_stop_types(tmp_path: Path, reason: str) -> None:
    envelope = Envelope(tmp_path / 'budget.sqlite3')
    envelope.settle(envelope.reserve(), 5000, 1000)
    envelope.stop(reason)
    with pytest.raises(ValueError, match='only a fixed case gate'):
        _acknowledge(envelope)
    assert envelope.snapshot()['stop_reason'] == reason
    with envelope.connect() as db:
        assert db.execute('SELECT count(*) FROM gate_resolutions').fetchone() == (0,)


@pytest.mark.parametrize('mismatch', ['unknown_usage', 'attempts', 'reserved', 'additional_stop'])
def test_gate_acknowledgment_rejects_uncertain_or_changed_accounting(tmp_path: Path, mismatch: str) -> None:
    envelope = Envelope(tmp_path / 'budget.sqlite3')
    attempt = envelope.reserve()
    if mismatch != 'unknown_usage':
        envelope.settle(attempt, 5000, 1000)
    envelope.stop('case_gate_failure')
    if mismatch == 'additional_stop':
        envelope.stop('missing_usage')
    before = envelope.snapshot()
    with pytest.raises(ValueError, match='only a fixed case gate'):
        _acknowledge(
            envelope,
            attempts=2 if mismatch == 'attempts' else 1,
            reserved=1 if mismatch == 'reserved' else 2475,
        )
    assert envelope.snapshot() == before
    with envelope.connect() as db:
        assert db.execute('SELECT count(*) FROM gate_resolutions').fetchone() == (0,)


def test_gate_acknowledgment_rejects_invalid_provenance_hash(tmp_path: Path) -> None:
    envelope = Envelope(tmp_path / 'budget.sqlite3')
    envelope.settle(envelope.reserve(), 5000, 1000)
    envelope.stop('case_gate_failure')
    with pytest.raises(ValueError, match='revision hashes'):
        envelope.acknowledge_fixed_case_gate(
            expected_attempts=1,
            expected_reserved_micro=2475,
            source_revision='not-a-revision',
            verification_sha256='b' * 64,
            manifest_sha256='c' * 64,
        )
    assert envelope.snapshot()['stop_reason'] == 'case_gate_failure'


def test_acknowledged_gate_does_not_create_more_spending_allowance(tmp_path: Path) -> None:
    envelope = Envelope(tmp_path / 'budget.sqlite3', cap_micro=12000)
    envelope.settle(envelope.reserve(), 24000, 4000)
    envelope.stop('case_gate_failure')
    _acknowledge(envelope, reserved=11000)
    with pytest.raises(RejectedError):
        envelope.reserve()
    assert envelope.snapshot() == {
        'attempts': 1,
        'reserved_micro_usd': 11000,
        'stop_reason': 'budget_or_attempt_limit',
    }


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


def test_explicit_attempt_ceiling_survives_zero_usage_and_reopen(tmp_path: Path) -> None:
    path = tmp_path / 'budget.sqlite3'
    envelope = Envelope(path, max_attempts=650)
    for _ in range(400):
        envelope.settle(envelope.reserve(), 0, 0)
    reopened = Envelope(path, max_attempts=650)
    assert reopened.max_attempts == 650
    assert reopened.reserve() == 401
    reopened.settle(401, 0, 0)
    for _ in range(249):
        reopened.settle(reopened.reserve(), 0, 0)
    with pytest.raises(RejectedError):
        reopened.reserve()
    assert reopened.snapshot() == {
        'attempts': 650,
        'reserved_micro_usd': 0,
        'stop_reason': 'budget_or_attempt_limit',
    }


def test_explicit_attempt_ceiling_never_increases_the_monetary_cap(tmp_path: Path) -> None:
    envelope = Envelope(tmp_path / 'budget.sqlite3', max_attempts=650)
    for _ in range(90):
        envelope.reserve()  # Unknown usage remains conservatively reserved.
    with pytest.raises(RejectedError):
        envelope.reserve()
    assert envelope.snapshot() == {
        'attempts': 90,
        'reserved_micro_usd': 990000,
        'stop_reason': 'budget_or_attempt_limit',
    }


def test_attempt_ceiling_cannot_change_after_initialization(tmp_path: Path) -> None:
    path = tmp_path / 'budget.sqlite3'
    original = Envelope(path, max_attempts=650)
    attempt = original.reserve()
    original.settle(attempt, 5000, 1000)
    before = original.snapshot()
    for attempted_limit in [None, 400, 649]:
        with pytest.raises(ValueError, match='attempt limit cannot be changed'):
            Envelope(path, max_attempts=attempted_limit)
    assert Envelope(path, max_attempts=650).snapshot() == before
    with closing(sqlite3.connect(path)) as db, db:
        assert db.execute('SELECT * FROM attempt_limits').fetchall() == [(1, 650)]
        assert db.execute('SELECT cap FROM limits').fetchall() == [(1000000,)]


def test_existing_default_attempt_ceiling_cannot_be_silently_raised(tmp_path: Path) -> None:
    path = tmp_path / 'budget.sqlite3'
    original = Envelope(path)
    assert original.max_attempts == 400
    with pytest.raises(ValueError, match='attempt limit cannot be changed'):
        Envelope(path, max_attempts=650)
    assert Envelope(path).snapshot() == {
        'attempts': 0,
        'reserved_micro_usd': 0,
        'stop_reason': None,
    }
    with pytest.raises(AttributeError):
        original.max_attempts = 650  # type: ignore[misc]


@pytest.mark.parametrize('limit', [True, False, 0, -1, 651, 1000, 1.5, '650'])
def test_invalid_attempt_ceiling_fails_before_creating_state(tmp_path: Path, limit: object) -> None:
    path = tmp_path / 'private' / 'budget.sqlite3'
    with pytest.raises(ValueError, match='integer between 1 and 650'):
        Envelope(path, max_attempts=limit)  # type: ignore[arg-type]
    assert not path.parent.exists()


def test_default_attempt_ceiling_is_resolved_at_construction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr('scripts.real_eval_budget.MAX_ATTEMPTS', 3)
    envelope = Envelope(tmp_path / 'budget.sqlite3')
    assert envelope.max_attempts == 3
    for _ in range(3):
        envelope.settle(envelope.reserve(), 0, 0)
    with pytest.raises(RejectedError):
        envelope.reserve()


def test_explicit_ceiling_initializes_legacy_metadata_without_rewriting_state(tmp_path: Path) -> None:
    path = tmp_path / 'budget.sqlite3'
    attempts = [(2, 11000, 0), (7, 2475, 1), (42, 0, 1)]
    status = [('AuthenticationError',), ('usage_exceeds_bound',)]
    with closing(sqlite3.connect(path)) as db, db:
        db.execute(
            'CREATE TABLE attempts (id INTEGER PRIMARY KEY, reserved INTEGER NOT NULL, '
            'settled INTEGER NOT NULL DEFAULT 0)'
        )
        db.execute('CREATE TABLE status (reason TEXT NOT NULL)')
        db.execute('CREATE TABLE limits (cap INTEGER NOT NULL)')
        db.executemany('INSERT INTO attempts VALUES (?,?,?)', attempts)
        db.executemany('INSERT INTO status VALUES (?)', status)
        db.execute('INSERT INTO limits VALUES (1000000)')
    envelope = Envelope(path, max_attempts=650)
    assert envelope.snapshot() == {
        'attempts': 3,
        'reserved_micro_usd': 13475,
        'stop_reason': 'AuthenticationError',
    }
    with pytest.raises(RejectedError):
        envelope.reserve()
    with closing(sqlite3.connect(path)) as db, db:
        assert db.execute('SELECT * FROM attempts ORDER BY id').fetchall() == attempts
        assert db.execute('SELECT * FROM status ORDER BY rowid').fetchall() == status
        assert db.execute('SELECT * FROM limits').fetchall() == [(1000000,)]
        assert db.execute('SELECT * FROM attempt_limits').fetchall() == [(1, 650)]


def test_legacy_metadata_initialization_rolls_back_on_monetary_cap_mismatch(tmp_path: Path) -> None:
    path = tmp_path / 'budget.sqlite3'
    with closing(sqlite3.connect(path)) as db, db:
        db.execute('CREATE TABLE limits (cap INTEGER NOT NULL)')
        db.execute('INSERT INTO limits VALUES (250000)')
    with pytest.raises(ValueError, match='evaluation cap cannot be changed'):
        Envelope(path, max_attempts=650)
    with closing(sqlite3.connect(path)) as db, db:
        assert db.execute('SELECT * FROM limits').fetchall() == [(250000,)]
        assert db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall() == [
            ('limits',)
        ]


def test_two_instances_share_the_persisted_attempt_ceiling_atomically(tmp_path: Path) -> None:
    path = tmp_path / 'budget.sqlite3'
    first = Envelope(path, max_attempts=650)
    second = Envelope(path, max_attempts=650)
    for _ in range(640):
        first.settle(first.reserve(), 0, 0)

    def attempt(index: int) -> bool:
        try:
            (first if index % 2 else second).reserve()
            return True
        except RejectedError:
            return False

    with ThreadPoolExecutor(max_workers=8) as pool:
        accepted = list(pool.map(attempt, range(30)))
    assert sum(accepted) == 10
    assert (
        first.snapshot()
        == second.snapshot()
        == {
            'attempts': 650,
            'reserved_micro_usd': 110000,
            'stop_reason': 'budget_or_attempt_limit',
        }
    )


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


def test_default_new_ledger_does_not_gain_audited_extension_metadata(tmp_path: Path) -> None:
    path = tmp_path / 'default.sqlite3'
    envelope = Envelope(path)
    assert envelope.max_attempts == 400 and envelope.cap_micro == 1000000
    with closing(sqlite3.connect(path)) as db:
        assert db.execute('SELECT max_attempts FROM attempt_limits').fetchall() == [(400,)]
        assert db.execute('SELECT cap FROM limits').fetchall() == [(1000000,)]
        assert (
            db.execute("SELECT name FROM sqlite_master WHERE name='authorized_envelope_extension'").fetchall()
            == []
        )
