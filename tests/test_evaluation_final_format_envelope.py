"""Third fixed audit event on synthetic disposable ledgers; no keys or providers."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest

from app.domain.errors import RejectedError
from scripts import extend_evaluation_envelope as cli
from scripts import real_eval_budget as budget
from tests.test_evaluation_followup_envelope import initial, migrate


def prior(tmp_path: Path) -> tuple[budget.Envelope, str]:
    old, first = initial(tmp_path)
    second = migrate(old, first)
    current = budget.Envelope.open_authorized(old.path, audit_sha256=second)
    current.settle(current.reserve(), 100, 100)
    return current, second


def snapshot(env: budget.Envelope, previous: str) -> dict[str, Any]:
    return budget.inspect_final_format_candidate(env.path, previous_audit_sha256=previous)


def extend(env: budget.Envelope, previous: str, expected: dict[str, Any] | None = None) -> str:
    return budget.extend_evaluation_final_format(
        env.path,
        previous_audit_sha256=previous,
        expected_snapshot=expected if expected is not None else snapshot(env, previous),
        authorization_ref='synthetic third owner approval2100 sameUSD6',
        authorization_sha256='1' * 64,
        source_revision='2' * 40,
        manifest_sha256='3' * 64,
    )


def rows(env: budget.Envelope) -> dict[str, Any]:
    with closing(sqlite3.connect(env.path)) as db:
        return {
            table: db.execute(f'SELECT * FROM {table} ORDER BY rowid').fetchall()  # noqa: S608 -- fixed test table names
            for table in (
                'attempts',
                'status',
                'gate_resolutions',
                'limits',
                'attempt_limits',
                'authorized_envelope_extension',
                'authorized_envelope_followup',
            )
        }


def test_third_event_preserves_every_old_row_and_requires_latest_audit(tmp_path: Path) -> None:
    old, second = prior(tmp_path)
    before = rows(old)
    final = extend(old, second)
    assert rows(old) == before
    current = budget.Envelope.open_authorized(old.path, audit_sha256=final)
    assert (current.max_attempts, current.cap_micro) == (2100, 6000000)
    assert current.snapshot() == old.snapshot()
    current.admit_new_run()
    with pytest.raises(ValueError, match='audit'):
        budget.Envelope.open_authorized(old.path, audit_sha256=second)
    with pytest.raises(ValueError, match='audit'):
        old.reserve()
    with pytest.raises(ValueError, match='explicit'):
        budget.Envelope(old.path, max_attempts=650)
    with closing(sqlite3.connect(old.path)) as db:
        record = json.loads(
            db.execute('SELECT record_json FROM authorized_envelope_final_format').fetchone()[0]
        )
    assert record['version'] == 3 and record['previous_audit_sha256'] == second
    assert record['old_cap_micro'] == record['new_cap_micro'] == 6000000
    assert (record['old_max_attempts'], record['new_max_attempts'], record['pending']) == (1600, 2100, 0)


def test_actual_2100_boundary_and_same_six_dollar_reservation_ceiling(tmp_path: Path) -> None:
    env, previous = prior(tmp_path)
    final = extend(env, previous)
    current = budget.Envelope.open_authorized(env.path, audit_sha256=final)
    with closing(sqlite3.connect(env.path)) as db, db:
        db.executemany('INSERT INTO attempts(reserved,settled) VALUES(0,1)', [()] * 2096)
    assert current.snapshot()['attempts'] == 2099
    current.settle(current.reserve(), 0, 0)
    with pytest.raises(RejectedError):
        current.reserve()
    assert current.snapshot()['attempts'] == 2100


def test_money_does_not_expand_or_refund_on_third_event(tmp_path: Path) -> None:
    env, previous = prior(tmp_path)
    final = extend(env, previous)
    current = budget.Envelope.open_authorized(env.path, audit_sha256=final)
    used = current.snapshot()['reserved_micro_usd']
    with closing(sqlite3.connect(env.path)) as db, db:
        db.execute('INSERT INTO attempts(reserved,settled) VALUES(?,1)', (6000000 - used - 1,))
    with pytest.raises(RejectedError):
        current.reserve()
    assert current.cap_micro == 6000000 and current.snapshot()['reserved_micro_usd'] == 5999999


@pytest.mark.parametrize(
    'fault',
    [
        'count',
        'cost',
        'hash',
        'pending_old',
        'pending_fresh',
        'unknown_stop',
        'interrupt_stop',
        'attempt_stop',
        'wrong_previous',
        'repeat',
    ],
)
def test_snapshot_pending_and_any_stop_block_extension_without_row_changes(
    tmp_path: Path, fault: str
) -> None:
    env, previous = prior(tmp_path)
    expected = snapshot(env, previous)
    if fault == 'count':
        expected['attempts'] += 1
    if fault == 'cost':
        expected['reserved_micro_usd'] += 1
    if fault == 'hash':
        expected['state_sha256'] = '0' * 64
    if fault.startswith('pending'):
        env.reserve()
        if fault == 'pending_fresh':
            expected = snapshot(env, previous)
    if fault.endswith('_stop'):
        env.stop(
            {
                'unknown_stop': 'provider_unknown_usage',
                'interrupt_stop': 'interrupted',
                'attempt_stop': 'budget_or_attempt_limit',
            }[fault]
        )
    if fault == 'wrong_previous':
        previous = '0' * 64
    if fault == 'repeat':
        extend(env, previous)
    before = rows(env)
    with pytest.raises(ValueError, match=r'mismatch|pending|stop|already|audit'):
        extend(env, previous, expected)
    assert rows(env) == before


@pytest.mark.parametrize(
    ('field', 'value'),
    [
        ('new_max_attempts', 1600),
        ('new_max_attempts', 2099),
        ('new_max_attempts', 2101),
        ('new_max_attempts', True),
        ('old_max_attempts', 1100),
        ('new_cap_micro', 6000001),
        ('new_cap_micro', 1000000),
        ('old_cap_micro', 1000000),
        ('pending', 1),
        ('version', 2),
    ],
)
def test_rehashed_lower_other_caps_or_pending_audit_are_not_authority(
    tmp_path: Path, field: str, value: object
) -> None:
    env, previous = prior(tmp_path)
    final = extend(env, previous)
    with closing(sqlite3.connect(env.path)) as db, db:
        record = json.loads(
            db.execute('SELECT record_json FROM authorized_envelope_final_format').fetchone()[0]
        )
        record[field] = value
        raw = budget._canonical(record)
        digest = hashlib.sha256(raw.encode()).hexdigest()
        db.execute('UPDATE authorized_envelope_final_format SET record_json=?,record_sha256=?', (raw, digest))
    with pytest.raises(ValueError, match=r'transition|integers'):
        budget.Envelope.open_authorized(env.path, audit_sha256=digest)
    with pytest.raises(ValueError, match=r'audit|historical'):
        budget.Envelope.open_authorized(env.path, audit_sha256=final)


@pytest.mark.parametrize(
    'fault',
    [
        'legacy_limit',
        'first_audit',
        'second_audit',
        'old_attempt',
        'latest_prefix',
        'missing_final',
        'multiple_final',
    ],
)
def test_all_three_prefixes_and_audit_cardinality_are_rechecked(tmp_path: Path, fault: str) -> None:
    env, previous = prior(tmp_path)
    final = extend(env, previous)
    current = budget.Envelope.open_authorized(env.path, audit_sha256=final)
    with closing(sqlite3.connect(env.path)) as db, db:
        if fault == 'legacy_limit':
            db.execute('UPDATE limits SET cap=6000000')
        if fault == 'first_audit':
            db.execute("UPDATE authorized_envelope_extension SET record_json='{}'")
        if fault == 'second_audit':
            db.execute("UPDATE authorized_envelope_followup SET record_json='{}'")
        if fault == 'old_attempt':
            db.execute('UPDATE attempts SET reserved=0 WHERE id=1')
        if fault == 'latest_prefix':
            db.execute('UPDATE attempts SET reserved=0 WHERE id=3')
        if fault == 'missing_final':
            db.execute('DELETE FROM authorized_envelope_final_format')
        if fault == 'multiple_final':
            audit = db.execute(
                'SELECT record_json,record_sha256 FROM authorized_envelope_final_format'
            ).fetchone()
            db.execute('DROP TABLE authorized_envelope_final_format')
            db.execute(
                'CREATE TABLE authorized_envelope_final_format(id INTEGER,record_json TEXT,record_sha256 TEXT)'
            )
            db.executemany(
                'INSERT INTO authorized_envelope_final_format VALUES(?,?,?)', [(1, *audit), (2, *audit)]
            )
    with pytest.raises(ValueError, match=r'audit|historical'):
        budget.Envelope.open_authorized(env.path, audit_sha256=final)
    with pytest.raises(ValueError, match=r'audit|historical'):
        current.reserve()


def test_owner_lock_and_failed_insert_roll_back_only_new_event(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env, previous = prior(tmp_path)
    expected, before = snapshot(env, previous), rows(env)
    with budget.evaluation_run_ownership(env.path), pytest.raises(ValueError, match='already owned'):
        extend(env, previous, expected)
    original = budget._insert_final_format

    def failed(db: sqlite3.Connection, record: dict[str, Any]) -> str:
        original(db, record)
        raise OSError('synthetic failure before commit')

    monkeypatch.setattr(budget, '_insert_final_format', failed)
    with pytest.raises(OSError, match='before commit'):
        extend(env, previous, expected)
    assert rows(env) == before
    with closing(sqlite3.connect(env.path)) as db:
        assert not budget._final_format_exists(db)
    assert budget.Envelope.open_authorized(env.path, audit_sha256=previous).max_attempts == 1600


def test_only_one_concurrent_third_event_commits(tmp_path: Path) -> None:
    env, previous = prior(tmp_path)
    expected = snapshot(env, previous)

    def run() -> str:
        try:
            return extend(env, previous, expected)
        except ValueError:
            return 'rejected'

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: run(), range(2)))
    assert results.count('rejected') == 1
    assert (
        budget.Envelope.open_authorized(
            env.path, audit_sha256=next(x for x in results if x != 'rejected')
        ).max_attempts
        == 2100
    )


def test_fresh_default_and_out_of_order_are_not_an_allowance(tmp_path: Path) -> None:
    folder = tmp_path / 'private'
    folder.mkdir(mode=0o700)
    fresh = budget.Envelope(folder / 'fresh.sqlite3')
    assert (fresh.max_attempts, fresh.cap_micro) == (400, 1000000)
    with pytest.raises(ValueError, match='no audited'):
        snapshot(fresh, 'a' * 64)
    with pytest.raises(ValueError, match='limit'):
        budget.Envelope(fresh.path, max_attempts=2100)


def test_fixed_cli_third_event_outputs_latest_hash_without_sdk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    env, previous = prior(tmp_path)
    expected = snapshot(env, previous)
    file = tmp_path / 'expected.json'
    file.write_text(json.dumps(expected))
    monkeypatch.setattr(
        'sys.argv',
        [
            'extend',
            'extend-2100-6-usd',
            '--budget-state',
            str(env.path),
            '--previous-audit-sha256',
            previous,
            '--expected-snapshot',
            str(file),
            '--authorization-ref',
            'synthetic third owner approval',
            '--authorization-sha256',
            '1' * 64,
            '--source-revision',
            '2' * 40,
            '--manifest-sha256',
            '3' * 64,
        ],
    )
    cli.main()
    result = json.loads(capsys.readouterr().out)
    assert result['new_max_attempts'] == 2100 and result['new_cap_micro'] == 6000000
    assert budget.Envelope.open_authorized(env.path, audit_sha256=result['audit_sha256']).max_attempts == 2100


@pytest.mark.parametrize('field', ['attempts', 'reserved_micro_usd', 'pending'])
def test_boolean_snapshot_fields_are_not_exact_integer_accounting(tmp_path: Path, field: str) -> None:
    env, previous = prior(tmp_path)
    expected = snapshot(env, previous)
    expected[field] = True
    before = rows(env)
    with pytest.raises(ValueError, match='integers'):
        extend(env, previous, expected)
    assert rows(env) == before


def test_even_exact_1600_attempt_stop_is_preserved_and_not_cleared(tmp_path: Path) -> None:
    env, previous = prior(tmp_path)
    with closing(sqlite3.connect(env.path)) as db, db:
        db.executemany('INSERT INTO attempts(reserved,settled) VALUES(0,1)', [()] * 1597)
    with pytest.raises(RejectedError):
        env.reserve()
    expected = snapshot(env, previous)
    assert expected['attempts'] == 1600 and expected['stop_reason'] == 'budget_or_attempt_limit'
    before = rows(env)
    with pytest.raises(ValueError, match='stop blocks'):
        extend(env, previous, expected)
    assert rows(env) == before
