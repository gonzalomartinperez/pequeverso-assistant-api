"""Synthetic second audit event; no real ledger, key or provider operation."""

from __future__ import annotations

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest

from scripts import extend_evaluation_envelope as cli
from scripts import real_eval_budget as budget


def initial(tmp_path: Path) -> tuple[budget.Envelope, str]:
    folder = tmp_path / 'private'
    folder.mkdir(mode=0o700)
    path = folder / 'ledger.sqlite3'
    legacy = budget.Envelope(path, max_attempts=650)
    legacy.settle(legacy.reserve(), 100, 100)
    first = budget.extend_evaluation_envelope(
        path,
        expected_snapshot=budget.inspect_extension_candidate(path),
        authorization_ref='synthetic first authorization',
        authorization_sha256='a' * 64,
        source_revision='b' * 40,
        manifest_sha256='c' * 64,
    )
    env = budget.Envelope.open_authorized(path, audit_sha256=first)
    env.settle(env.reserve(), 100, 100)
    return env, first


def snapshot(env: budget.Envelope, previous: str) -> dict[str, Any]:
    return budget.inspect_followup_candidate(env.path, previous_audit_sha256=previous)


def migrate(env: budget.Envelope, previous: str, expected: dict[str, Any] | None = None) -> str:
    return budget.extend_evaluation_followup(
        env.path,
        previous_audit_sha256=previous,
        expected_snapshot=expected or snapshot(env, previous),
        authorization_ref='synthetic second owner authorization',
        authorization_sha256='d' * 64,
        source_revision='e' * 40,
        manifest_sha256='f' * 64,
    )


def preserved(env: budget.Envelope) -> dict[str, Any]:
    with closing(sqlite3.connect(env.path)) as db:
        return {
            table: db.execute(f'SELECT * FROM {table} ORDER BY rowid').fetchall()  # noqa: S608 -- fixed table names
            for table in (
                'attempts',
                'status',
                'gate_resolutions',
                'limits',
                'attempt_limits',
                'authorized_envelope_extension',
            )
        }


def test_second_event_preserves_first_and_requires_final_hash(tmp_path: Path) -> None:
    old, previous = initial(tmp_path)
    before = preserved(old)
    final = migrate(old, previous)
    assert preserved(old) == before
    with pytest.raises(ValueError, match='final evaluation audit'):
        budget.Envelope.open_authorized(old.path, audit_sha256=previous)
    with pytest.raises(ValueError, match='final evaluation audit'):
        old.reserve()
    with pytest.raises(ValueError, match='explicit'):
        budget.Envelope(old.path, max_attempts=650)
    current = budget.Envelope.open_authorized(old.path, audit_sha256=final)
    assert (current.max_attempts, current.cap_micro) == (1600, 6000000)
    current.admit_new_run()
    with closing(sqlite3.connect(old.path)) as db:
        record = json.loads(db.execute('SELECT record_json FROM authorized_envelope_followup').fetchone()[0])
    assert record['previous_audit_sha256'] == previous
    assert record['old_cap_micro'] == record['new_cap_micro'] == 6000000
    assert record['authorization_sha256'] == 'd' * 64


def test_actual_reservation_boundary_is_1600_with_unchanged_money(tmp_path: Path) -> None:
    env, previous = initial(tmp_path)
    final = migrate(env, previous)
    env = budget.Envelope.open_authorized(env.path, audit_sha256=final)
    with closing(sqlite3.connect(env.path)) as db, db:
        db.executemany('INSERT INTO attempts(reserved,settled) VALUES(0,1)', [()] * 1597)
    assert env.snapshot()['attempts'] == 1599
    env.settle(env.reserve(), 0, 0)
    assert env.snapshot()['attempts'] == 1600
    with pytest.raises(budget.RejectedError):
        env.reserve()
    assert env.snapshot()['attempts'] == 1600


def test_money_ceiling_never_expands(tmp_path: Path) -> None:
    env, previous = initial(tmp_path)
    final = migrate(env, previous)
    env = budget.Envelope.open_authorized(env.path, audit_sha256=final)
    with closing(sqlite3.connect(env.path)) as db, db:
        db.execute('INSERT INTO attempts(reserved,settled) VALUES(5999500,1)')
    with pytest.raises(budget.RejectedError):
        env.reserve()
    assert env.cap_micro == 6000000


@pytest.mark.parametrize(
    'fault', ['count', 'cost', 'hash', 'pending', 'stop', 'unknown_stop', 'wrong_previous', 'repeat']
)
def test_changed_snapshot_pending_stop_previous_and_repeat_fail_closed(tmp_path: Path, fault: str) -> None:
    env, previous = initial(tmp_path)
    expected = snapshot(env, previous)
    if fault == 'count':
        expected['attempts'] += 1
    if fault == 'cost':
        expected['reserved_micro_usd'] += 1
    if fault == 'hash':
        expected['state_sha256'] = '0' * 64
    if fault == 'pending':
        env.reserve()
    if fault == 'stop':
        env.stop('interrupted')
    if fault == 'unknown_stop':
        env.stop('provider_unknown_usage')
    if fault == 'wrong_previous':
        previous = '0' * 64
    if fault == 'repeat':
        migrate(env, previous)
    before = preserved(env)
    with pytest.raises(ValueError, match=r'mismatch|blocks followup|already exists'):
        migrate(env, previous, expected)
    assert preserved(env) == before


@pytest.mark.parametrize(
    'mutation',
    ['first_audit', 'first_attempt', 'second_prefix_attempt', 'legacy_cap', 'final_audit', 'cardinality'],
)
def test_both_prefixes_audit_and_cardinality_are_rechecked(tmp_path: Path, mutation: str) -> None:
    env, previous = initial(tmp_path)
    final = migrate(env, previous)
    current = budget.Envelope.open_authorized(env.path, audit_sha256=final)
    with closing(sqlite3.connect(env.path)) as db, db:
        if mutation == 'first_audit':
            db.execute("UPDATE authorized_envelope_extension SET record_json='{}'")
        if mutation == 'first_attempt':
            db.execute('UPDATE attempts SET reserved=0 WHERE id=1')
        if mutation == 'second_prefix_attempt':
            db.execute('UPDATE attempts SET reserved=0 WHERE id=2')
        if mutation == 'legacy_cap':
            db.execute('UPDATE limits SET cap=6000000')
        if mutation == 'final_audit':
            db.execute("UPDATE authorized_envelope_followup SET record_json='{}'")
        if mutation == 'cardinality':
            db.execute('DELETE FROM authorized_envelope_followup')
    with pytest.raises(ValueError, match=r'audit|historical'):
        budget.Envelope.open_authorized(env.path, audit_sha256=final)
    with pytest.raises(ValueError, match=r'audit|historical'):
        current.reserve()


def test_insert_failure_rolls_back_and_owner_lock_excludes_concurrent_migration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env, previous = initial(tmp_path)
    expected = snapshot(env, previous)
    before = preserved(env)
    with budget.evaluation_run_ownership(env.path), pytest.raises(ValueError, match='already owned'):
        migrate(env, previous, expected)
    insert = budget._insert_followup

    def fail(db: sqlite3.Connection, record: dict[str, Any]) -> str:
        insert(db, record)
        raise OSError('synthetic fsync failure before commit')

    monkeypatch.setattr(budget, '_insert_followup', fail)
    with pytest.raises(OSError, match='before commit'):
        migrate(env, previous, expected)
    assert preserved(env) == before
    with closing(sqlite3.connect(env.path)) as db:
        assert not budget._followup_exists(db)
    assert budget.Envelope.open_authorized(env.path, audit_sha256=previous).max_attempts == 1100


def test_exactly_one_concurrent_followup_commits(tmp_path: Path) -> None:
    env, previous = initial(tmp_path)
    expected = snapshot(env, previous)

    def attempt() -> str:
        try:
            return migrate(env, previous, expected)
        except ValueError:
            return 'rejected'

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(lambda _: attempt(), range(2)))
    assert results.count('rejected') == 1
    assert (
        budget.Envelope.open_authorized(
            env.path, audit_sha256=next(x for x in results if x != 'rejected')
        ).max_attempts
        == 1600
    )


def test_fresh_default_and_out_of_order_followup_are_never_an_allowance(tmp_path: Path) -> None:
    folder = tmp_path / 'private'
    folder.mkdir(mode=0o700)
    env = budget.Envelope(folder / 'fresh.sqlite3')
    assert (env.max_attempts, env.cap_micro) == (400, 1000000)
    with pytest.raises(ValueError, match='no audited'):
        snapshot(env, 'a' * 64)
    with closing(sqlite3.connect(env.path)) as db, db:
        db.execute(
            'CREATE TABLE authorized_envelope_followup(id INTEGER, record_json TEXT, record_sha256 TEXT)'
        )
        db.execute("INSERT INTO authorized_envelope_followup VALUES(1,'{}','a')")
    with pytest.raises(ValueError, match='explicit'):
        budget.Envelope(env.path)
    with pytest.raises(ValueError, match='audit'):
        budget.Envelope.open_authorized(env.path, audit_sha256='a' * 64)


def test_followup_cli_uses_exact_snapshot_and_final_receipt_without_sdk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    env, previous = initial(tmp_path)

    def no_sdk(*args: Any, **kwargs: Any) -> None:
        pytest.fail('offline CLI constructed SDK')

    monkeypatch.setattr(budget, 'AsyncOpenAI', no_sdk)
    monkeypatch.setattr(
        'sys.argv',
        ['extend', 'inspect-followup', '--budget-state', str(env.path), '--previous-audit-sha256', previous],
    )
    cli.main()
    expected = json.loads(capsys.readouterr().out)
    expected_path = env.path.with_name('snapshot.json')
    expected_path.write_text(json.dumps(expected))
    expected_path.chmod(0o600)
    monkeypatch.setattr(
        'sys.argv',
        [
            'extend',
            'extend-1600-6-usd',
            '--budget-state',
            str(env.path),
            '--previous-audit-sha256',
            previous,
            '--expected-snapshot',
            str(expected_path),
            '--authorization-ref',
            'synthetic owner',
            '--authorization-sha256',
            'd' * 64,
            '--source-revision',
            'e' * 40,
            '--manifest-sha256',
            'f' * 64,
        ],
    )
    cli.main()
    receipt = json.loads(capsys.readouterr().out)
    assert receipt['new_max_attempts'] == 1600 and receipt['new_cap_micro'] == 6000000
    assert (
        budget.Envelope.open_authorized(env.path, audit_sha256=receipt['audit_sha256']).max_attempts == 1600
    )


def at_attempt_limit(tmp_path: Path) -> tuple[budget.Envelope, str]:
    env, previous = initial(tmp_path)
    with closing(sqlite3.connect(env.path)) as db, db:
        db.executemany('INSERT INTO attempts(reserved,settled) VALUES(0,1)', [()] * 1098)
    with pytest.raises(budget.RejectedError):
        env.reserve()
    assert env.snapshot()['attempts'] == 1100
    assert env.snapshot()['stop_reason'] == 'budget_or_attempt_limit'
    return env, previous


def test_only_the_exact_attempt_limit_is_atomically_resolved_by_new_owner_event(tmp_path: Path) -> None:
    env, previous = at_attempt_limit(tmp_path)
    before = preserved(env)
    final = migrate(env, previous)
    after = preserved(env)
    assert {k: v for k, v in after.items() if k != 'gate_resolutions'} == {
        k: v for k, v in before.items() if k != 'gate_resolutions'
    }
    resolution = after['gate_resolutions'][-1]
    assert resolution[1:] == ('budget_or_attempt_limit', 'e' * 40, 'd' * 64, 'f' * 64, 1100, 276)
    current = budget.Envelope.open_authorized(env.path, audit_sha256=final)
    assert current.snapshot()['stop_reason'] is None
    current.admit_new_run()
    current.settle(current.reserve(), 0, 0)
    assert current.snapshot()['attempts'] == 1101
    assert current.cap_micro == 6000000


@pytest.mark.parametrize('fault', ['money_limit', 'pending', 'other_stop', 'two_stops', 'wrong_count'])
def test_second_event_never_clears_a_monetary_or_uncertain_or_unrelated_stop(
    tmp_path: Path, fault: str
) -> None:
    env, previous = at_attempt_limit(tmp_path)
    with closing(sqlite3.connect(env.path)) as db, db:
        if fault == 'money_limit':
            db.execute('UPDATE attempts SET reserved=5999000 WHERE id=1100')
        if fault == 'pending':
            db.execute('UPDATE attempts SET settled=0 WHERE id=1100')
        if fault == 'other_stop':
            db.execute("UPDATE status SET reason='provider_unknown_usage'")
        if fault == 'two_stops':
            db.execute("INSERT INTO status VALUES ('interrupted')")
        if fault == 'wrong_count':
            db.execute('DELETE FROM attempts WHERE id=1100')
    before = preserved(env)
    with pytest.raises(ValueError, match=r'pending|only an exact attempt-limit'):
        migrate(env, previous)
    assert preserved(env) == before
    assert before['gate_resolutions'] == []


def test_followup_failure_rolls_back_both_resolution_and_second_event(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env, previous = at_attempt_limit(tmp_path)
    before = preserved(env)
    original = budget._insert_followup

    def fail(db: sqlite3.Connection, record: dict[str, Any]) -> str:
        original(db, record)
        raise OSError('synthetic failure after both inserts')

    monkeypatch.setattr(budget, '_insert_followup', fail)
    with pytest.raises(OSError, match='after both inserts'):
        migrate(env, previous)
    assert preserved(env) == before
    with closing(sqlite3.connect(env.path)) as db:
        assert not budget._followup_exists(db)


def test_attempt_limit_resolution_is_part_of_the_sealed_prefix(tmp_path: Path) -> None:
    env, previous = at_attempt_limit(tmp_path)
    final = migrate(env, previous)
    with closing(sqlite3.connect(env.path)) as db, db:
        db.execute('UPDATE gate_resolutions SET verification_sha256=?', ('0' * 64,))
    with pytest.raises(ValueError, match='resolution'):
        budget.Envelope.open_authorized(env.path, audit_sha256=final)


@pytest.mark.parametrize(
    'field', ['new_max_attempts', 'new_cap_micro', 'old_max_attempts', 'version', 'extra']
)
def test_rehashed_but_out_of_policy_events_are_not_authority(tmp_path: Path, field: str) -> None:
    env, previous = initial(tmp_path)
    migrate(env, previous)
    with closing(sqlite3.connect(env.path)) as db, db:
        record = json.loads(db.execute('SELECT record_json FROM authorized_envelope_followup').fetchone()[0])
        record[field] = 9999999
        raw = budget._canonical(record)
        import hashlib

        digest = hashlib.sha256(raw.encode()).hexdigest()
        db.execute('UPDATE authorized_envelope_followup SET record_json=?,record_sha256=?', (raw, digest))
    with pytest.raises(ValueError, match=r'outside|invalid followup audit'):
        budget.Envelope.open_authorized(env.path, audit_sha256=digest)


def test_multiple_followup_events_are_rejected_even_with_a_valid_first_hash(tmp_path: Path) -> None:
    env, previous = initial(tmp_path)
    final = migrate(env, previous)
    with closing(sqlite3.connect(env.path)) as db, db:
        row = db.execute('SELECT record_json,record_sha256 FROM authorized_envelope_followup').fetchone()
        db.execute('DROP TABLE authorized_envelope_followup')
        db.execute(
            'CREATE TABLE authorized_envelope_followup(id INTEGER,record_json TEXT,record_sha256 TEXT)'
        )
        db.executemany('INSERT INTO authorized_envelope_followup VALUES (?,?,?)', [(1, *row), (2, *row)])
    with pytest.raises(ValueError, match='cardinality'):
        budget.Envelope.open_authorized(env.path, audit_sha256=final)
