"""Synthetic private ledgers only: an auditable, atomic, owner-locked extension, never SDK I/O."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest

from scripts import real_eval_budget as budget
from scripts.evaluate_end_to_end import load_live_provider


def ledger(tmp_path: Path) -> tuple[Path, budget.Envelope]:
    folder = tmp_path / 'private'
    folder.mkdir(mode=0o700)
    path = folder / 'evaluation.sqlite3'
    envelope = budget.Envelope(path, max_attempts=650)
    for _ in range(3):
        envelope.settle(envelope.reserve(), 100, 100)
    return path, envelope


def migrate(path: Path, snapshot: dict[str, Any] | None = None) -> str:
    return budget.extend_evaluation_envelope(
        path,
        expected_snapshot=snapshot or budget.inspect_extension_candidate(path),
        authorization_ref='synthetic owner approval',
        authorization_sha256='a' * 64,
        source_revision='b' * 40,
        manifest_sha256='c' * 64,
    )


def rows(path: Path) -> dict[str, object]:
    with closing(sqlite3.connect(path)) as db:
        return {
            table: db.execute(f'SELECT * FROM {table} ORDER BY rowid').fetchall()  # noqa: S608 -- fixed table names
            for table in ('attempts', 'status', 'limits', 'attempt_limits', 'gate_resolutions')
        }


def test_extension_preserves_all_legacy_rows_and_uses_explicit_immutable_audit(tmp_path: Path) -> None:
    path, old = ledger(tmp_path)
    before = rows(path)
    digest = migrate(path)
    assert rows(path) == before
    with pytest.raises(ValueError, match='explicit'):
        budget.Envelope(path, max_attempts=650)
    with pytest.raises(ValueError, match='stale'):
        old.reserve()
    extended = budget.Envelope.open_authorized(path, audit_sha256=digest)
    assert (extended.max_attempts, extended.cap_micro) == (1100, 6000000)
    assert extended.snapshot() == old.snapshot()
    # Settled zero usage does not reset the attempt counter, and ceiling1100 is real.
    for _ in range(1097):
        extended.settle(extended.reserve(), 0, 0)
    with pytest.raises(budget.RejectedError):
        extended.reserve()
    assert extended.snapshot()['attempts'] == 1100
    with closing(sqlite3.connect(path)) as db:
        raw, saved = db.execute(
            'SELECT record_json,record_sha256 FROM authorized_envelope_extension'
        ).fetchone()
        assert hashlib.sha256(raw.encode()).hexdigest() == digest == saved
        audit = json.loads(raw)
        assert audit['old_cap_micro'] == 1000000 and audit['old_max_attempts'] == 650
        assert audit['authorization_ref'] == 'synthetic owner approval'
        assert audit['source_revision'] == 'b' * 40 and audit['manifest_sha256'] == 'c' * 64


@pytest.mark.parametrize('fault', ['count', 'spend', 'hash', 'pending', 'stop', 'budget', 'default', 'empty'])
def test_extension_rejects_snapshot_pending_stop_budget_and_unapproved_legacy_limits(
    tmp_path: Path,
    fault: str,
) -> None:
    path, envelope = ledger(tmp_path)
    snapshot = budget.inspect_extension_candidate(path)
    if fault == 'count':
        snapshot['attempts'] += 1
    if fault == 'spend':
        snapshot['reserved_micro_usd'] += 1
    if fault == 'hash':
        snapshot['state_sha256'] = 'd' * 64
    if fault == 'pending':
        envelope.reserve()
    if fault == 'stop':
        envelope.stop('case_gate_failure')
    if fault in ('budget', 'default', 'empty'):
        with closing(sqlite3.connect(path)) as db, db:
            if fault == 'budget':
                db.execute('UPDATE attempts SET reserved=1000001 WHERE id=1')
            if fault == 'default':
                db.execute('UPDATE attempt_limits SET max_attempts=400')
            if fault == 'empty':
                db.execute('DELETE FROM attempts')
        snapshot = budget.inspect_extension_candidate(path)
    before = rows(path)
    with pytest.raises(ValueError, match='blocks extension'):
        migrate(path, snapshot)
    assert rows(path) == before
    with closing(sqlite3.connect(path)) as db:
        assert not db.execute(
            "SELECT name FROM sqlite_master WHERE name='authorized_envelope_extension'"
        ).fetchall()


def test_extension_preserves_resolved_gate_and_status_identities(tmp_path: Path) -> None:
    path, env = ledger(tmp_path)
    env.stop('case_gate_failure')
    snapshot = env.snapshot()
    env.acknowledge_fixed_case_gate(
        expected_attempts=3,
        expected_reserved_micro=snapshot['reserved_micro_usd'],
        source_revision='b' * 40,
        verification_sha256='d' * 64,
        manifest_sha256='c' * 64,
    )
    before = rows(path)
    digest = migrate(path)
    assert rows(path) == before
    budget.Envelope.open_authorized(path, audit_sha256=digest).admit_new_run()


def test_repeated_migration_and_wrong_audit_never_replace_authority(tmp_path: Path) -> None:
    path, _ = ledger(tmp_path)
    expected = budget.inspect_extension_candidate(path)
    digest = migrate(path, expected)
    with pytest.raises(ValueError, match='already exists'):
        migrate(path, expected)
    with pytest.raises(ValueError, match='mismatch'):
        budget.Envelope.open_authorized(path, audit_sha256='d' * 64)
    assert budget.Envelope.open_authorized(path, audit_sha256=digest).max_attempts == 1100


def test_transaction_rollback_leaves_no_partial_audit_or_allowance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path, _ = ledger(tmp_path)
    before = rows(path)
    original = budget._insert_extension

    def interrupted(db: sqlite3.Connection, record: dict[str, Any]) -> str:
        original(db, record)
        raise OSError('synthetic disk failure before commit')

    monkeypatch.setattr(budget, '_insert_extension', interrupted)
    with pytest.raises(OSError, match='before commit'):
        migrate(path)
    assert rows(path) == before
    with closing(sqlite3.connect(path)) as db:
        assert not db.execute(
            "SELECT name FROM sqlite_master WHERE name='authorized_envelope_extension'"
        ).fetchall()
    assert budget.Envelope(path, max_attempts=650).max_attempts == 650


def test_owner_lock_excludes_extension_and_reservations_revalidate_after_migration(tmp_path: Path) -> None:
    path, stale = ledger(tmp_path)
    expected = budget.inspect_extension_candidate(path)
    with (
        budget.evaluation_run_ownership(path),
        ThreadPoolExecutor(max_workers=1) as pool,
        pytest.raises(ValueError, match='already owned'),
    ):
        pool.submit(migrate, path, expected).result()
    digest = migrate(path, expected)
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(stale.reserve) for _ in range(4)]
        for f in futures:
            with pytest.raises(ValueError, match='stale'):
                f.result()
    assert budget.Envelope.open_authorized(path, audit_sha256=digest).snapshot()['attempts'] == 3


@pytest.mark.parametrize('mutation', ['attempt', 'status', 'resolution', 'legacy_cap', 'audit'])
def test_reopen_and_reserve_fail_closed_on_historical_or_audit_tampering(
    tmp_path: Path, mutation: str
) -> None:
    path, env = ledger(tmp_path)
    env.stop('case_gate_failure')
    env.acknowledge_fixed_case_gate(
        expected_attempts=3,
        expected_reserved_micro=env.snapshot()['reserved_micro_usd'],
        source_revision='b' * 40,
        verification_sha256='d' * 64,
        manifest_sha256='c' * 64,
    )
    digest = migrate(path)
    owner = budget.Envelope.open_authorized(path, audit_sha256=digest)
    with closing(sqlite3.connect(path)) as db, db:
        if mutation == 'attempt':
            db.execute('UPDATE attempts SET reserved=0 WHERE id=1')
        if mutation == 'status':
            db.execute("UPDATE status SET reason='replaced'")
        if mutation == 'resolution':
            db.execute('UPDATE gate_resolutions SET source_revision=?', ('e' * 40,))
        if mutation == 'legacy_cap':
            db.execute('UPDATE limits SET cap=6000000')
        if mutation == 'audit':
            db.execute("UPDATE authorized_envelope_extension SET record_json='{}'")
    with pytest.raises(ValueError, match=r'historical|audit'):
        budget.Envelope.open_authorized(path, audit_sha256=digest)
    with pytest.raises(ValueError, match=r'historical|audit'):
        owner.reserve()


def test_fresh_or_manually_raised_allowance_is_impossible_without_migration(tmp_path: Path) -> None:
    missing = tmp_path / 'absent' / 'budget.sqlite3'
    with pytest.raises(ValueError, match='existing external'):
        budget.Envelope.open_authorized(missing, audit_sha256='a' * 64)
    assert not missing.parent.exists()
    with pytest.raises(ValueError, match='at most 1 USD'):
        budget.Envelope(missing, 6000000, max_attempts=1100)
    assert not missing.parent.exists()
    path, env = ledger(tmp_path)
    env.cap_micro = 6000000
    with pytest.raises(ValueError, match='persisted'):
        env.reserve()
    assert budget.MAX_ATTEMPTS == 400 and budget.CAP_MICRO == 1000000
    with pytest.raises(ValueError, match='at most 1 USD'):
        budget.Envelope(path, 6000000, max_attempts=1100)


def test_audited_loader_validates_before_reading_synthetic_key_and_uses_persisted_limits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path, _ = ledger(tmp_path)
    digest = migrate(path)
    key = path.parent / 'synthetic-key.txt'
    key.write_text('not a credential')
    key.chmod(0o600)
    reads: list[Path] = []

    def values(file: Path, *, interpolate: bool) -> dict[str, str]:
        reads.append(file)
        return {
            'OPENAI_API_KEY': 'synthetic-only',
            'OPENAI_MODEL': 'gpt-6-luna',
            'OPENAI_REASONING_EFFORT': 'medium',
        }

    monkeypatch.setattr('scripts.evaluate_end_to_end.dotenv_values', values)
    with pytest.raises(ValueError, match='exact audit'):
        load_live_provider(key, path, authorized_envelope_sha256='invalid')
    with pytest.raises(ValueError, match='mismatch'):
        load_live_provider(key, path, authorized_envelope_sha256='d' * 64)
    assert reads == []
    provider = load_live_provider(key, path, authorized_envelope_sha256=digest)
    assert provider.envelope.cap_micro == 6000000 and provider.envelope.max_attempts == 1100
    assert reads == [key]


def test_extended_money_bound_is_still_atomic_and_unknown_usage_never_refunded(tmp_path: Path) -> None:
    path, _ = ledger(tmp_path)
    digest = migrate(path)
    owner = budget.Envelope.open_authorized(path, audit_sha256=digest)
    for _ in range(545):
        owner.reserve()
    with pytest.raises(budget.RejectedError):
        owner.reserve()
    assert owner.snapshot() == {
        'attempts': 548,
        'reserved_micro_usd': 5995414,
        'stop_reason': 'budget_or_attempt_limit',
    }
    with pytest.raises(budget.RejectedError):
        budget.Envelope.open_authorized(path, audit_sha256=digest).admit_new_run()


def test_two_migrators_can_commit_only_one_authority(tmp_path: Path) -> None:
    path, _ = ledger(tmp_path)
    expected = budget.inspect_extension_candidate(path)

    def candidate() -> str:
        try:
            return migrate(path, expected)
        except ValueError:
            return 'rejected'

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: candidate(), range(2)))
    assert outcomes.count('rejected') == 1
    digest = next(v for v in outcomes if v != 'rejected')
    assert budget.Envelope.open_authorized(path, audit_sha256=digest).snapshot()['attempts'] == 3
    with closing(sqlite3.connect(path)) as db:
        assert db.execute('SELECT count(*) FROM authorized_envelope_extension').fetchone() == (1,)
