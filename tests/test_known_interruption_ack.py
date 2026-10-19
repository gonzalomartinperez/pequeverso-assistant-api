"""Offline synthetic ledger acknowledgment, never an automatic retry or new allowance."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest

from scripts import real_eval_budget as budget


def make_ledger(tmp_path: Path, *, extended: bool = False) -> budget.Envelope:
    folder = tmp_path / 'private'
    folder.mkdir(mode=0o700)
    path = folder / 'budget.sqlite3'
    env = budget.Envelope(path, max_attempts=650)
    env.settle(env.reserve(), 100, 100)
    if extended:
        digest = budget.extend_evaluation_envelope(
            path,
            expected_snapshot=budget.inspect_extension_candidate(path),
            authorization_ref='synthetic authorization',
            authorization_sha256='a' * 64,
            source_revision='b' * 40,
            manifest_sha256='c' * 64,
        )
        env = budget.Envelope.open_authorized(path, audit_sha256=digest)
        env.settle(env.reserve(), 100, 100)
    env.stop('interrupted')
    return env


def ack(env: budget.Envelope, **overrides: Any) -> None:
    snapshot = env.snapshot()
    args = {
        'expected_attempts': snapshot['attempts'],
        'expected_reserved_micro': snapshot['reserved_micro_usd'],
        'source_revision': 'd' * 40,
        'verification_sha256': 'e' * 64,
        'manifest_sha256': 'f' * 64,
    }
    args.update(overrides)
    env.acknowledge_known_interruption(**args)


def original_rows(env: budget.Envelope) -> dict[str, Any]:
    with closing(sqlite3.connect(env.path)) as db:
        tables = ['attempts', 'status', 'limits', 'attempt_limits']
        if budget._extension_exists(db):
            tables.append('authorized_envelope_extension')
        return {
            table: db.execute(f'SELECT * FROM {table} ORDER BY rowid').fetchall()  # noqa: S608 -- fixed tables only
            for table in tables
        }


@pytest.mark.parametrize('extended', [False, True])
def test_known_interruption_is_append_only_and_never_dispatches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, extended: bool
) -> None:
    env = make_ledger(tmp_path, extended=extended)
    before = original_rows(env)

    def no_sdk(*args: Any, **kwargs: Any) -> None:
        pytest.fail('offline acknowledgment must not construct a provider SDK')

    monkeypatch.setattr(budget, 'AsyncOpenAI', no_sdk)
    ack(env)
    assert original_rows(env) == before
    assert env.snapshot()['stop_reason'] is None
    env.admit_new_run()
    with closing(sqlite3.connect(env.path)) as db:
        assert db.execute(
            'SELECT reason,source_revision,verification_sha256,manifest_sha256 FROM gate_resolutions'
        ).fetchall() == [('interrupted', 'd' * 40, 'e' * 64, 'f' * 64)]
    assert env.snapshot()['attempts'] == (2 if extended else 1)
    assert (env.max_attempts, env.cap_micro) == ((1100, 6000000) if extended else (650, 1000000))
    with pytest.raises(ValueError, match='only one interruption'):
        ack(env)


@pytest.mark.parametrize(
    'reason',
    [
        'authentication',
        'provider_error',
        'budget_or_attempt_limit',
        'historical_unreported_usage',
        'case_gate_failure',
        'duplicate_usage',
        'embedding_unreported_usage',
        'interrupted_extra',
    ],
)
def test_every_other_stop_remains_blocking(tmp_path: Path, reason: str) -> None:
    env = make_ledger(tmp_path)
    with closing(sqlite3.connect(env.path)) as db, db:
        db.execute('UPDATE status SET reason=?', (reason,))
    before = original_rows(env)
    with pytest.raises(ValueError, match='only one interruption'):
        ack(env)
    assert original_rows(env) == before
    assert env.snapshot()['stop_reason'] == reason


@pytest.mark.parametrize(
    'fault', ['attempt_count', 'cost', 'pending', 'two_stops', 'attempt_ceiling', 'budget', 'no_stop']
)
def test_changed_or_uncertain_accounting_cannot_be_acknowledged(tmp_path: Path, fault: str) -> None:
    env = make_ledger(tmp_path)
    kwargs: dict[str, Any] = {}
    with closing(sqlite3.connect(env.path)) as db, db:
        if fault == 'attempt_count':
            kwargs['expected_attempts'] = 2
        elif fault == 'cost':
            kwargs['expected_reserved_micro'] = 0
        elif fault == 'pending':
            db.execute('UPDATE attempts SET settled=0')
        elif fault == 'two_stops':
            db.execute("INSERT INTO status VALUES ('interrupted')")
        elif fault == 'attempt_ceiling':
            db.executemany('INSERT INTO attempts(reserved,settled) VALUES (0,1)', [()] * 649)
        elif fault == 'budget':
            db.execute('UPDATE attempts SET reserved=1000000')
        elif fault == 'no_stop':
            db.execute('DELETE FROM status')
    before = original_rows(env)
    with pytest.raises(ValueError, match='only one interruption'):
        ack(env, **kwargs)
    assert original_rows(env) == before
    with closing(sqlite3.connect(env.path)) as db:
        assert db.execute('SELECT count(*) FROM gate_resolutions').fetchone() == (0,)


@pytest.mark.parametrize(
    ('key', 'value'),
    [
        ('expected_attempts', True),
        ('expected_attempts', 0),
        ('expected_reserved_micro', -1),
        ('expected_reserved_micro', True),
        ('source_revision', 'x' * 40),
        ('verification_sha256', 'A' * 64),
        ('manifest_sha256', 'f' * 63),
    ],
)
def test_invalid_snapshot_or_provenance_is_rejected(tmp_path: Path, key: str, value: Any) -> None:
    env = make_ledger(tmp_path)
    with pytest.raises(ValueError, match=r'exact existing accounting|exact lowercase'):
        ack(env, **{key: value})
    assert env.snapshot()['stop_reason'] == 'interrupted'


def test_concurrent_owner_and_insert_failure_preserve_the_original_stop(tmp_path: Path) -> None:
    env = make_ledger(tmp_path)
    before = original_rows(env)
    with budget.evaluation_run_ownership(env.path), pytest.raises(ValueError, match='already owned'):
        ack(env)
    assert original_rows(env) == before
    with closing(sqlite3.connect(env.path)) as db, db:
        db.execute(
            "CREATE TRIGGER fail_resolution BEFORE INSERT ON gate_resolutions BEGIN SELECT RAISE(ABORT,'synthetic insert failure'); END"
        )
    with pytest.raises(sqlite3.IntegrityError, match='synthetic insert failure'):
        ack(env)
    assert original_rows(env) == before
    assert env.snapshot()['stop_reason'] == 'interrupted'
    with closing(sqlite3.connect(env.path)) as db:
        assert db.execute('SELECT count(*) FROM gate_resolutions').fetchone() == (0,)


def test_audit_prefix_tampering_cannot_be_resolved_as_an_interruption(tmp_path: Path) -> None:
    env = make_ledger(tmp_path, extended=True)
    with closing(sqlite3.connect(env.path)) as db, db:
        db.execute('UPDATE attempts SET reserved=0 WHERE id=1')
    before = original_rows(env)
    with pytest.raises(ValueError, match='historical'):
        ack(env)
    assert original_rows(env) == before


def test_prior_resolutions_and_extended_audit_survive_the_new_ack(tmp_path: Path) -> None:
    env = make_ledger(tmp_path)
    with closing(sqlite3.connect(env.path)) as db, db:
        db.execute("UPDATE status SET reason='case_gate_failure'")
    env.acknowledge_fixed_case_gate(
        expected_attempts=1,
        expected_reserved_micro=env.snapshot()['reserved_micro_usd'],
        source_revision='1' * 40,
        verification_sha256='2' * 64,
        manifest_sha256='3' * 64,
    )
    digest = budget.extend_evaluation_envelope(
        env.path,
        expected_snapshot=budget.inspect_extension_candidate(env.path),
        authorization_ref='synthetic owner',
        authorization_sha256='a' * 64,
        source_revision='b' * 40,
        manifest_sha256='c' * 64,
    )
    env = budget.Envelope.open_authorized(env.path, audit_sha256=digest)
    env.stop('interrupted')
    with closing(sqlite3.connect(env.path)) as db:
        prior = db.execute('SELECT * FROM gate_resolutions ORDER BY status_rowid').fetchall()
    before = original_rows(env)
    ack(env)
    assert original_rows(env) == before
    with closing(sqlite3.connect(env.path)) as db:
        resolutions = db.execute('SELECT * FROM gate_resolutions ORDER BY status_rowid').fetchall()
    assert resolutions[:-1] == prior
    assert resolutions[-1][1] == 'interrupted'
    budget.Envelope.open_authorized(env.path, audit_sha256=digest).admit_new_run()
