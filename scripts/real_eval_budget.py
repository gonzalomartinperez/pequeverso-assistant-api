"""Independent conservative envelope for one explicitly authorized local evaluation.

Unknown usage, cancellation and failure retain the full allocation. Known usage is
settled at conservative rates including Fast and regional premiums. This is an evaluation helper, not a billing setting.
"""

from __future__ import annotations

import asyncio
import fcntl
import hashlib
import json
import os
import sqlite3
import stat
from collections.abc import AsyncGenerator, Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_CEILING, Decimal
from pathlib import Path
from typing import Any

import httpx2 as httpx
import openai
from openai import AsyncOpenAI

from app.adapters.providers.openai_provider import OpenAIResponsesProvider
from app.ai.provider import ModelChunk, ModelRequest, UsageChunk
from app.application.knowledge_ports import EmbeddingAccounting
from app.domain.errors import FailureCode, RejectedError
from app.domain.knowledge import EmbeddingPurpose

MODEL = 'gpt-6-luna'
ATTEMPT_MICRO = 11000
MAX_ATTEMPTS = 400
CAP_MICRO = 1000000


@contextmanager
def evaluation_run_ownership(path: Path) -> Iterator[None]:
    """One stop-first local evaluation owner; never unlink its stable lock inode."""
    root = Path(__file__).resolve().parents[1]
    if path.is_symlink() or path.resolve().is_relative_to(root):
        raise ValueError('evaluation ownership requires an external private budget path')
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory = path.parent.stat()
    if stat.S_IMODE(directory.st_mode) != 0o700 or directory.st_uid != os.getuid():
        raise ValueError('evaluation ownership directory must be private and owned')
    lock = path.with_name(path.name + '.owner.lock')
    descriptor = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or metadata.st_uid != os.getuid()
        ):
            raise ValueError('evaluation ownership file must be private and owned')
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('evaluation budget is already owned by another runner') from None
        try:
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
    finally:
        os.close(descriptor)


class Envelope:
    def __init__(self, path: Path, cap_micro: int = CAP_MICRO, *, max_attempts: int | None = None) -> None:
        if not 0 < cap_micro <= CAP_MICRO:
            raise ValueError('evaluation cap must be positive and at most 1 USD')
        attempt_limit = MAX_ATTEMPTS if max_attempts is None else max_attempts
        if type(attempt_limit) is not int or not 1 <= attempt_limit <= 650:
            raise ValueError('evaluation attempt limit must be an integer between 1 and 650')
        self._extension_sha256: str | None = None
        self.cap_micro = cap_micro
        self._max_attempts = attempt_limit
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = path
        with self.connect() as db:
            if _extension_exists(db) or _followup_exists(db) or _final_format_exists(db):
                raise ValueError('audited extension requires explicit open_authorized and audit SHA256')
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('BEGIN IMMEDIATE')
            db.execute(
                'CREATE TABLE IF NOT EXISTS attempts (id INTEGER PRIMARY KEY, reserved INTEGER NOT NULL, settled INTEGER NOT NULL DEFAULT 0)'
            )
            db.execute('CREATE TABLE IF NOT EXISTS status (reason TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS limits (cap INTEGER NOT NULL)')
            saved = db.execute('SELECT cap FROM limits LIMIT 1').fetchone()
            if saved is not None and saved[0] != cap_micro:
                raise ValueError('existing evaluation cap cannot be changed')
            if saved is None:
                db.execute('INSERT INTO limits (cap) VALUES (?)', (cap_micro,))
            # Independent metadata leaves the legacy ledger and monetary cap untouched.
            # Adding it to an old ledger requires an explicit owner-authorized procedure;
            # configuring this helper never grants permission to read keys or make calls.
            db.execute(
                'CREATE TABLE IF NOT EXISTS attempt_limits '
                '(id INTEGER PRIMARY KEY CHECK (id=1), max_attempts INTEGER NOT NULL '
                "CHECK (typeof(max_attempts)='integer' AND max_attempts BETWEEN 1 AND 650))"
            )
            saved_attempt_limit = db.execute('SELECT max_attempts FROM attempt_limits WHERE id=1').fetchone()
            if saved_attempt_limit is not None and saved_attempt_limit[0] != attempt_limit:
                raise ValueError('existing evaluation attempt limit cannot be changed')
            if saved_attempt_limit is None:
                db.execute('INSERT INTO attempt_limits (id,max_attempts) VALUES (1,?)', (attempt_limit,))
            db.execute(
                'CREATE TABLE IF NOT EXISTS gate_resolutions ('
                'status_rowid INTEGER PRIMARY KEY, reason TEXT NOT NULL, '
                'source_revision TEXT NOT NULL, verification_sha256 TEXT NOT NULL, '
                'manifest_sha256 TEXT NOT NULL, attempts INTEGER NOT NULL, '
                'reserved_micro INTEGER NOT NULL)'
            )
        path.chmod(0o600)

    @classmethod
    def open_authorized(cls, path: Path, *, audit_sha256: str) -> Envelope:
        """Open only an existing audited extension; never create or migrate an allowance."""
        _exact_hash(audit_sha256, 64)
        _private_existing_ledger(path)
        instance = cls.__new__(cls)
        instance.path = path
        instance._extension_sha256 = audit_sha256
        with instance.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            record = _verified_extension(db, audit_sha256)
        instance.cap_micro = record['new_cap_micro']
        instance._max_attempts = record['new_max_attempts']
        return instance

    def _assert_effective_limits(self, db: sqlite3.Connection) -> None:
        """Recheck under the reservation transaction; old objects cannot bypass migration."""
        if self._extension_sha256 is not None:
            record = _verified_extension(db, self._extension_sha256)
            if (self.cap_micro, self.max_attempts) != (record['new_cap_micro'], record['new_max_attempts']):
                raise ValueError('effective evaluation limits cannot be changed')
        elif _extension_exists(db) or _followup_exists(db) or _final_format_exists(db):
            raise ValueError('stale evaluation owner must reopen the audited extension explicitly')
        elif (
            self.cap_micro > CAP_MICRO
            or not 1 <= self.max_attempts <= 650
            or db.execute('SELECT cap FROM limits').fetchall() != [(self.cap_micro,)]
            or db.execute('SELECT id,max_attempts FROM attempt_limits').fetchall() != [(1, self.max_attempts)]
        ):
            raise ValueError('persisted evaluation limits cannot be changed')

    @property
    def max_attempts(self) -> int:
        """The persisted, immutable attempt ceiling; independent of the monetary cap."""
        return self._max_attempts

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=10)
        try:
            db.execute('PRAGMA synchronous=FULL')
            with db:
                yield db
        finally:
            db.close()

    def snapshot(self) -> dict[str, Any]:
        with self.connect() as db:
            count, reserved = db.execute(
                'SELECT count(*), coalesce(sum(reserved),0) FROM attempts'
            ).fetchone()
            stopped = db.execute(
                'SELECT s.reason FROM status s WHERE NOT EXISTS '
                '(SELECT 1 FROM gate_resolutions r WHERE r.status_rowid=s.rowid '
                'AND r.reason=s.reason) ORDER BY s.rowid LIMIT 1'
            ).fetchone()
        return {
            'attempts': count,
            'reserved_micro_usd': reserved,
            'stop_reason': stopped[0] if stopped else None,
        }

    def stop(self, reason: str) -> None:
        with self.connect() as db:
            db.execute('INSERT INTO status (reason) VALUES (?)', (reason,))

    def admit_new_run(self) -> None:
        """Reject a restarted run with unknown historical spend before any new SDK I/O.

        This is entry admission, not per-request admission: an in-flight request in
        this exclusively owned run legitimately has an unsettled reservation.
        """
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            self._assert_effective_limits(db)
            pending = db.execute('SELECT 1 FROM attempts WHERE settled=0 LIMIT 1').fetchone()
            stopped = db.execute(
                'SELECT 1 FROM status s WHERE NOT EXISTS '
                '(SELECT 1 FROM gate_resolutions r WHERE r.status_rowid=s.rowid '
                'AND r.reason=s.reason) LIMIT 1'
            ).fetchone()
            if pending and not stopped:
                db.execute('INSERT INTO status(reason) VALUES (?)', ('historical_unreported_usage',))
            rejected = bool(pending or stopped)
        if rejected:
            raise RejectedError(FailureCode.BUDGET_EXHAUSTED)

    def acknowledge_fixed_case_gate(
        self,
        *,
        expected_attempts: int,
        expected_reserved_micro: int,
        source_revision: str,
        verification_sha256: str,
        manifest_sha256: str,
    ) -> None:
        """Explicit operator acknowledgment after an authorized fix, never an automatic retry.

        Preserve the original stop row and every monetary/attempt record. Only a known-usage
        case gate is eligible; authentication, provider, budget and unknown-usage stops remain
        blocking. Hashes identify independently verified code and a separately frozen phase;
        they do not grant permission or prove that verification occurred. Keep ledger rows
        append-only; do not delete status rows or rewrite their identities.
        """
        if (
            type(expected_attempts) is not int
            or expected_attempts < 1
            or type(expected_reserved_micro) is not int
            or expected_reserved_micro < 0
        ):
            raise ValueError('gate acknowledgment requires exact existing accounting')
        for value, size in (
            (source_revision, 40),
            (verification_sha256, 64),
            (manifest_sha256, 64),
        ):
            if len(value) != size or any(c not in '0123456789abcdef' for c in value):
                raise ValueError('gate acknowledgment requires exact lowercase revision hashes')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            active = db.execute(
                'SELECT s.rowid,s.reason FROM status s WHERE NOT EXISTS '
                '(SELECT 1 FROM gate_resolutions r WHERE r.status_rowid=s.rowid '
                'AND r.reason=s.reason) ORDER BY s.rowid'
            ).fetchall()
            accounting = db.execute(
                'SELECT count(*),coalesce(sum(reserved),0),'
                'sum(CASE WHEN settled=0 THEN 1 ELSE 0 END) FROM attempts'
            ).fetchone()
            if (
                len(active) != 1
                or active[0][1] != 'case_gate_failure'
                or accounting != (expected_attempts, expected_reserved_micro, 0)
            ):
                raise ValueError('only a fixed case gate with unchanged known usage can be acknowledged')
            db.execute(
                'INSERT INTO gate_resolutions VALUES (?,?,?,?,?,?,?)',
                (
                    active[0][0],
                    active[0][1],
                    source_revision,
                    verification_sha256,
                    manifest_sha256,
                    expected_attempts,
                    expected_reserved_micro,
                ),
            )

    def acknowledge_known_interruption(
        self,
        *,
        expected_attempts: int,
        expected_reserved_micro: int,
        source_revision: str,
        verification_sha256: str,
        manifest_sha256: str,
    ) -> None:
        """Offline operator acknowledgment of one interruption with all usage known.

        Never dispatch, settle/refund usage, retry, change limits or remove a stop.
        Provenance identifies operator evidence; it is not payment authorization.
        """
        if (
            type(expected_attempts) is not int
            or expected_attempts < 1
            or type(expected_reserved_micro) is not int
            or expected_reserved_micro < 0
        ):
            raise ValueError('interruption acknowledgment requires exact existing accounting')
        for value, size in (
            (source_revision, 40),
            (verification_sha256, 64),
            (manifest_sha256, 64),
        ):
            _exact_hash(value, size)
        _private_existing_ledger(self.path)
        with evaluation_run_ownership(self.path), self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            self._assert_effective_limits(db)
            active = db.execute(
                'SELECT s.rowid,s.reason FROM status s WHERE NOT EXISTS '
                '(SELECT 1 FROM gate_resolutions r WHERE r.status_rowid=s.rowid '
                'AND r.reason=s.reason) ORDER BY s.rowid'
            ).fetchall()
            accounting = db.execute(
                'SELECT count(*),coalesce(sum(reserved),0),'
                'sum(CASE WHEN settled=0 THEN 1 ELSE 0 END) FROM attempts'
            ).fetchone()
            if (
                len(active) != 1
                or active[0][1] != 'interrupted'
                or accounting != (expected_attempts, expected_reserved_micro, 0)
                or expected_attempts >= self.max_attempts
                or expected_reserved_micro + ATTEMPT_MICRO > self.cap_micro
            ):
                raise ValueError(
                    'only one interruption with unchanged known usage and remaining budget is eligible'
                )
            db.execute(
                'INSERT INTO gate_resolutions VALUES (?,?,?,?,?,?,?)',
                (
                    active[0][0],
                    active[0][1],
                    source_revision,
                    verification_sha256,
                    manifest_sha256,
                    expected_attempts,
                    expected_reserved_micro,
                ),
            )

    def settle(self, attempt: int, inputs: int, outputs: int) -> None:
        if (
            type(inputs) is not int
            or type(outputs) is not int
            or not (0 <= inputs <= 24000 and 0 <= outputs <= 4000)
        ):
            with self.connect() as db:
                db.execute(
                    'UPDATE attempts SET reserved=max(reserved,?) WHERE id=?', (ATTEMPT_MICRO, attempt)
                )
            self.stop('usage_exceeds_bound')
            return
        amount = int(
            (Decimal(inputs) * Decimal('0.275') + Decimal(outputs) * Decimal('1.1')).to_integral_value(
                rounding=ROUND_CEILING
            )
        )
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT reserved, settled FROM attempts WHERE id=?', (attempt,)).fetchone()
            if row is None:
                raise ValueError('unknown evaluation attempt')
            if row[1]:
                db.execute('UPDATE attempts SET reserved=max(reserved,?) WHERE id=?', (amount, attempt))
                db.execute('INSERT INTO status (reason) VALUES (?)', ('duplicate_usage',))
            else:
                db.execute('UPDATE attempts SET reserved=?, settled=1 WHERE id=?', (amount, attempt))

    def reserve(self) -> int:
        attempt = None
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            self._assert_effective_limits(db)
            stopped = db.execute(
                'SELECT s.reason FROM status s WHERE NOT EXISTS '
                '(SELECT 1 FROM gate_resolutions r WHERE r.status_rowid=s.rowid '
                'AND r.reason=s.reason) ORDER BY s.rowid LIMIT 1'
            ).fetchone()
            count, used = db.execute('SELECT count(*), coalesce(sum(reserved),0) FROM attempts').fetchone()
            if not stopped and count < self.max_attempts and used + ATTEMPT_MICRO <= self.cap_micro:
                cursor = db.execute('INSERT INTO attempts (reserved) VALUES (?)', (ATTEMPT_MICRO,))
                attempt = cursor.lastrowid
            elif not stopped:
                db.execute('INSERT INTO status (reason) VALUES (?)', ('budget_or_attempt_limit',))
        if attempt is None:
            raise RejectedError(FailureCode.BUDGET_EXHAUSTED)
        return attempt

    def settle_embedding(self, attempt: int, inputs: int, *, input_byte_bound: int) -> bool:
        """Settle one previously reserved SDK attempt; never change the shared allowance.

        Every embedding request first reserves the same USD0.011 as generation. Known
        input usage settles at USD0.044/M (2.2x Standard); unknown usage keeps USD0.011.
        The caller must retain the exact UTF-8 bound from before dispatch.
        """
        if (
            type(inputs) is not int
            or type(input_byte_bound) is not int
            or not 0 <= inputs <= input_byte_bound <= 240000
            or input_byte_bound == 0
        ):
            with self.connect() as db:
                db.execute(
                    'UPDATE attempts SET reserved=max(reserved,?) WHERE id=?', (ATTEMPT_MICRO, attempt)
                )
            self.stop('embedding_usage_exceeds_bound')
            return False
        amount = int((Decimal(inputs) * Decimal('0.044')).to_integral_value(rounding=ROUND_CEILING))
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT reserved,settled FROM attempts WHERE id=?', (attempt,)).fetchone()
            if row is None:
                raise ValueError('unknown evaluation attempt')
            if row[1]:
                db.execute('UPDATE attempts SET reserved=max(reserved,?) WHERE id=?', (amount, attempt))
                db.execute('INSERT INTO status(reason) VALUES (?)', ('duplicate_usage',))
                return False
            db.execute('UPDATE attempts SET reserved=?,settled=1 WHERE id=?', (amount, attempt))
        return True


_EXTENSION_TABLE = 'authorized_envelope_extension'
_EXTENSION_TARGET = (1100, 6000000)
_EXTENSION_FIELDS = frozenset(
    {
        'version',
        'old_cap_micro',
        'old_max_attempts',
        'new_cap_micro',
        'new_max_attempts',
        'attempts',
        'reserved_micro_usd',
        'last_attempt_id',
        'last_status_rowid',
        'state_sha256',
        'authorization_ref',
        'authorization_sha256',
        'source_revision',
        'manifest_sha256',
        'created_at',
    }
)


def _exact_hash(value: str, length: int) -> None:
    if not isinstance(value, str) or len(value) != length or any(c not in '0123456789abcdef' for c in value):
        raise ValueError('exact lowercase revision/SHA256 required')


def _private_existing_ledger(path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    if path.is_symlink() or path.resolve().is_relative_to(root) or not path.is_file():
        raise ValueError('extension requires the existing external private ledger')
    metadata = path.stat()
    directory = path.parent.stat()
    if (
        not stat.S_ISREG(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or metadata.st_uid != os.getuid()
        or metadata.st_nlink != 1
        or stat.S_IMODE(directory.st_mode) != 0o700
        or directory.st_uid != os.getuid()
    ):
        raise ValueError('extension ledger/directory must be private and owned')


def _extension_exists(db: sqlite3.Connection) -> bool:
    return (
        db.execute(
            'SELECT 1 FROM sqlite_master WHERE type=? AND name=?', ('table', _EXTENSION_TABLE)
        ).fetchone()
        is not None
    )


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True)


def _historical_state(
    db: sqlite3.Connection, *, attempt_id: int | None = None, status_rowid: int | None = None
) -> dict[str, Any]:
    attempts = db.execute(
        'SELECT id,reserved,settled FROM attempts WHERE (? IS NULL OR id<=?) ORDER BY id',
        (attempt_id, attempt_id),
    ).fetchall()
    statuses = db.execute(
        'SELECT rowid,reason FROM status WHERE (? IS NULL OR rowid<=?) ORDER BY rowid',
        (status_rowid, status_rowid),
    ).fetchall()
    resolutions = db.execute(
        'SELECT * FROM gate_resolutions WHERE (? IS NULL OR status_rowid<=?) ORDER BY status_rowid',
        (status_rowid, status_rowid),
    ).fetchall()
    return {
        'attempts': attempts,
        'status': statuses,
        'gate_resolutions': resolutions,
        'limits': db.execute('SELECT cap FROM limits ORDER BY rowid').fetchall(),
        'attempt_limits': db.execute('SELECT id,max_attempts FROM attempt_limits ORDER BY id').fetchall(),
    }


def _state_hash(state: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical(state).encode()).hexdigest()


def _snapshot(db: sqlite3.Connection) -> dict[str, Any]:
    state = _historical_state(db)
    attempts = state['attempts']
    if any(type(value) is not int or value < 0 for row in attempts for value in row):
        raise ValueError('invalid historical accounting')
    if any(row[2] not in (0, 1) for row in attempts):
        raise ValueError('invalid historical settlement')
    stopped = db.execute(
        'SELECT s.reason FROM status s WHERE NOT EXISTS '
        '(SELECT 1 FROM gate_resolutions r WHERE r.status_rowid=s.rowid AND r.reason=s.reason) '
        'ORDER BY s.rowid LIMIT 1'
    ).fetchone()
    return {
        'attempts': len(attempts),
        'reserved_micro_usd': sum(row[1] for row in attempts),
        'pending': sum(row[2] == 0 for row in attempts),
        'stop_reason': stopped[0] if stopped else None,
        'state_sha256': _state_hash(state),
    }


def inspect_extension_candidate(path: Path) -> dict[str, Any]:
    """Private offline snapshot, no keys/provider; stable owner lock even for this read."""
    _private_existing_ledger(path)
    with (
        evaluation_run_ownership(path),
        closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)) as db,
    ):
        db.execute('BEGIN')
        if _extension_exists(db) or _followup_exists(db) or _final_format_exists(db):
            raise ValueError('evaluation extension already exists')
        return _snapshot(db)


def _verified_extension(db: sqlite3.Connection, expected_sha256: str) -> dict[str, Any]:
    if _final_format_exists(db):
        return _verified_final_format(db, expected_sha256)
    if _followup_exists(db):
        return _verified_followup(db, expected_sha256)
    return _verified_first_extension(db, expected_sha256)


def _verified_first_extension(
    db: sqlite3.Connection, expected_sha256: str, *, effective_max_attempts: int = 1100
) -> dict[str, Any]:
    if not _extension_exists(db):
        raise ValueError('no audited evaluation extension exists')
    rows = db.execute('SELECT id,record_json,record_sha256 FROM authorized_envelope_extension').fetchall()
    if len(rows) != 1 or rows[0][0] != 1:
        raise ValueError('invalid extension audit cardinality')
    _, raw, stored_hash = rows[0]
    if (
        not isinstance(raw, str)
        or hashlib.sha256(raw.encode()).hexdigest() != stored_hash
        or stored_hash != expected_sha256
    ):
        raise ValueError('evaluation extension audit SHA256 mismatch')
    record = json.loads(raw)
    if not isinstance(record, dict) or set(record) != _EXTENSION_FIELDS or _canonical(record) != raw:
        raise ValueError('invalid extension audit record')
    integers = (
        'version',
        'old_cap_micro',
        'old_max_attempts',
        'new_cap_micro',
        'new_max_attempts',
        'attempts',
        'reserved_micro_usd',
        'last_attempt_id',
        'last_status_rowid',
    )
    if any(type(record[key]) is not int or record[key] < 0 for key in integers):
        raise ValueError('invalid extension audit integers')
    if (
        record['version'] != 1
        or (record['old_max_attempts'], record['old_cap_micro']) != (650, CAP_MICRO)
        or (record['new_max_attempts'], record['new_cap_micro']) != _EXTENSION_TARGET
        or record['attempts'] < 1
        or record['attempts'] > 650
        or record['reserved_micro_usd'] > CAP_MICRO
    ):
        raise ValueError('extension is outside the exact authorized transition')
    for key, length in (
        ('state_sha256', 64),
        ('authorization_sha256', 64),
        ('source_revision', 40),
        ('manifest_sha256', 64),
    ):
        _exact_hash(record[key], length)
    if (
        not isinstance(record['authorization_ref'], str)
        or not record['authorization_ref'].strip()
        or len(record['authorization_ref']) > 512
    ):
        raise ValueError('authorization reference is required')
    if not isinstance(record['created_at'], str):
        raise TypeError('extension timestamp required')
    original = _historical_state(
        db, attempt_id=record['last_attempt_id'], status_rowid=record['last_status_rowid']
    )
    if (
        original['limits'] != [(CAP_MICRO,)]
        or original['attempt_limits'] != [(1, 650)]
        or _state_hash(original) != record['state_sha256']
        or len(original['attempts']) != record['attempts']
        or sum(row[1] for row in original['attempts']) != record['reserved_micro_usd']
    ):
        raise ValueError('historical evaluation prefix or legacy limits changed')
    current = _snapshot(db)
    if (
        current['attempts'] < record['attempts']
        or current['attempts'] > effective_max_attempts
        or current['reserved_micro_usd'] > 6000000
    ):
        raise ValueError('current accounting exceeds the authorized extension')
    return record


def _insert_extension(db: sqlite3.Connection, record: dict[str, Any]) -> str:
    raw = _canonical(record)
    digest = hashlib.sha256(raw.encode()).hexdigest()
    db.execute(
        'CREATE TABLE authorized_envelope_extension (id INTEGER PRIMARY KEY CHECK(id=1), '
        'record_json TEXT NOT NULL, record_sha256 TEXT NOT NULL)'
    )
    db.execute('INSERT INTO authorized_envelope_extension VALUES (1,?,?)', (raw, digest))
    return digest


def extend_evaluation_envelope(
    path: Path,
    *,
    expected_snapshot: dict[str, Any],
    authorization_ref: str,
    authorization_sha256: str,
    source_revision: str,
    manifest_sha256: str,
) -> str:
    """The one explicit offline 650/$1→1100/$6 migration; all old tables remain intact."""
    _private_existing_ledger(path)
    for value, size in ((authorization_sha256, 64), (source_revision, 40), (manifest_sha256, 64)):
        _exact_hash(value, size)
    if (
        not isinstance(authorization_ref, str)
        or not authorization_ref.strip()
        or len(authorization_ref) > 512
    ):
        raise ValueError('authorization reference is required')
    if set(expected_snapshot) != {'attempts', 'reserved_micro_usd', 'pending', 'stop_reason', 'state_sha256'}:
        raise ValueError('exact full expected snapshot required')
    _exact_hash(expected_snapshot['state_sha256'], 64)
    for key in ('attempts', 'reserved_micro_usd', 'pending'):
        if type(expected_snapshot[key]) is not int:
            raise ValueError('snapshot integers must be exact')
    with evaluation_run_ownership(path), closing(sqlite3.connect(path, timeout=10)) as db, db:
        db.execute('PRAGMA synchronous=FULL')
        db.execute('BEGIN IMMEDIATE')
        if _extension_exists(db) or _followup_exists(db) or _final_format_exists(db):
            raise ValueError('evaluation extension already exists')
        snapshot = _snapshot(db)
        state = _historical_state(db)
        if (
            snapshot != expected_snapshot
            or not 1 <= snapshot['attempts'] <= 650
            or snapshot['reserved_micro_usd'] > CAP_MICRO
            or snapshot['pending']
            or snapshot['stop_reason'] is not None
            or state['limits'] != [(CAP_MICRO,)]
            or state['attempt_limits'] != [(1, 650)]
        ):
            raise ValueError(
                'snapshot mismatch, pending usage, stop, budget or legacy limit blocks extension'
            )
        record = {
            'version': 1,
            'old_cap_micro': CAP_MICRO,
            'old_max_attempts': 650,
            'new_cap_micro': 6000000,
            'new_max_attempts': 1100,
            'attempts': snapshot['attempts'],
            'reserved_micro_usd': snapshot['reserved_micro_usd'],
            'last_attempt_id': state['attempts'][-1][0],
            'last_status_rowid': state['status'][-1][0] if state['status'] else 0,
            'state_sha256': snapshot['state_sha256'],
            'authorization_ref': authorization_ref,
            'authorization_sha256': authorization_sha256,
            'source_revision': source_revision,
            'manifest_sha256': manifest_sha256,
            'created_at': datetime.now(UTC).isoformat(),
        }
        digest = _insert_extension(db, record)
        _verified_extension(db, digest)
    return digest


_FOLLOWUP_TABLE = 'authorized_envelope_followup'
_FOLLOWUP_FIELDS = _EXTENSION_FIELDS | {'previous_audit_sha256', 'resolved_attempt_limit_status_rowid'}


def _followup_exists(db: sqlite3.Connection) -> bool:
    return (
        db.execute(
            'SELECT 1 FROM sqlite_master WHERE type=? AND name=?', ('table', _FOLLOWUP_TABLE)
        ).fetchone()
        is not None
    )


def _followup_state(
    db: sqlite3.Connection, *, attempt_id: int | None = None, status_rowid: int | None = None
) -> dict[str, Any]:
    return {
        'legacy': _historical_state(db, attempt_id=attempt_id, status_rowid=status_rowid),
        'first_extension': db.execute(
            'SELECT id,record_json,record_sha256 FROM authorized_envelope_extension ORDER BY id'
        ).fetchall(),
    }


def _followup_snapshot(db: sqlite3.Connection) -> dict[str, Any]:
    snapshot = _snapshot(db)
    snapshot['state_sha256'] = _state_hash(_followup_state(db))
    return snapshot


def inspect_followup_candidate(path: Path, *, previous_audit_sha256: str) -> dict[str, Any]:
    """Offline exact snapshot for the fixed second event, never a new allowance."""
    _exact_hash(previous_audit_sha256, 64)
    _private_existing_ledger(path)
    with (
        evaluation_run_ownership(path),
        closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)) as db,
    ):
        db.execute('BEGIN')
        if _followup_exists(db) or _final_format_exists(db):
            raise ValueError('evaluation followup already exists')
        _verified_first_extension(db, previous_audit_sha256)
        return _followup_snapshot(db)


def _verified_followup(
    db: sqlite3.Connection, expected_sha256: str, *, effective_max_attempts: int = 1600
) -> dict[str, Any]:
    rows = db.execute('SELECT id,record_json,record_sha256 FROM authorized_envelope_followup').fetchall()
    if len(rows) != 1 or rows[0][0] != 1:
        raise ValueError('invalid followup audit cardinality')
    _, raw, digest = rows[0]
    if (
        not isinstance(raw, str)
        or hashlib.sha256(raw.encode()).hexdigest() != digest
        or digest != expected_sha256
    ):
        raise ValueError('final evaluation audit SHA256 mismatch')
    record = json.loads(raw)
    if not isinstance(record, dict) or set(record) != _FOLLOWUP_FIELDS or _canonical(record) != raw:
        raise ValueError('invalid followup audit record')
    for key in (
        'version',
        'old_cap_micro',
        'old_max_attempts',
        'new_cap_micro',
        'new_max_attempts',
        'attempts',
        'reserved_micro_usd',
        'last_attempt_id',
        'last_status_rowid',
        'resolved_attempt_limit_status_rowid',
    ):
        if type(record[key]) is not int or record[key] < 0:
            raise ValueError('invalid followup audit integers')
    if (
        record['version'] != 2
        or (record['old_max_attempts'], record['new_max_attempts']) != (1100, 1600)
        or (record['old_cap_micro'], record['new_cap_micro']) != (6000000, 6000000)
        or not 1 <= record['attempts'] <= 1100
        or record['reserved_micro_usd'] > 6000000
    ):
        raise ValueError('followup is outside the exact authorized transition')
    for key, size in (
        ('previous_audit_sha256', 64),
        ('state_sha256', 64),
        ('authorization_sha256', 64),
        ('source_revision', 40),
        ('manifest_sha256', 64),
    ):
        _exact_hash(record[key], size)
    if (
        not isinstance(record['authorization_ref'], str)
        or not record['authorization_ref'].strip()
        or len(record['authorization_ref']) > 512
        or not isinstance(record['created_at'], str)
    ):
        raise ValueError('followup authorization reference and timestamp required')
    resolved = record['resolved_attempt_limit_status_rowid']
    if resolved:
        resolution = db.execute(
            'SELECT reason,source_revision,verification_sha256,manifest_sha256,attempts,reserved_micro '
            'FROM gate_resolutions WHERE status_rowid=?',
            (resolved,),
        ).fetchone()
        status = db.execute('SELECT reason FROM status WHERE rowid=?', (resolved,)).fetchone()
        if (
            status != ('budget_or_attempt_limit',)
            or resolution
            != (
                'budget_or_attempt_limit',
                record['source_revision'],
                record['authorization_sha256'],
                record['manifest_sha256'],
                record['attempts'],
                record['reserved_micro_usd'],
            )
            or record['attempts'] != 1100
            or record['reserved_micro_usd'] + ATTEMPT_MICRO > 6000000
            or resolved > record['last_status_rowid']
        ):
            raise ValueError('invalid exact attempt-limit resolution in followup')
    # The second verified event alone permits the larger current count. Event one
    # and its historical prefix still retain their original exact limits/bytes.
    _verified_first_extension(
        db, record['previous_audit_sha256'], effective_max_attempts=effective_max_attempts
    )
    original = _followup_state(
        db, attempt_id=record['last_attempt_id'], status_rowid=record['last_status_rowid']
    )
    attempts = original['legacy']['attempts']
    if (
        _state_hash(original) != record['state_sha256']
        or len(attempts) != record['attempts']
        or sum(row[1] for row in attempts) != record['reserved_micro_usd']
    ):
        raise ValueError('followup historical prefix changed')
    current = _snapshot(db)
    if (
        current['attempts'] < record['attempts']
        or current['attempts'] > effective_max_attempts
        or current['reserved_micro_usd'] > 6000000
    ):
        raise ValueError('current accounting exceeds the authorized followup')
    return record


def _insert_followup(db: sqlite3.Connection, record: dict[str, Any]) -> str:
    raw = _canonical(record)
    digest = hashlib.sha256(raw.encode()).hexdigest()
    db.execute(
        'CREATE TABLE authorized_envelope_followup (id INTEGER PRIMARY KEY CHECK(id=1), '
        'record_json TEXT NOT NULL, record_sha256 TEXT NOT NULL)'
    )
    db.execute('INSERT INTO authorized_envelope_followup VALUES (1,?,?)', (raw, digest))
    return digest


def extend_evaluation_followup(
    path: Path,
    *,
    previous_audit_sha256: str,
    expected_snapshot: dict[str, Any],
    authorization_ref: str,
    authorization_sha256: str,
    source_revision: str,
    manifest_sha256: str,
) -> str:
    """Fixed offline 1100→1600 event; USD6 and every earlier row stay unchanged."""
    _private_existing_ledger(path)
    for value, size in (
        (previous_audit_sha256, 64),
        (authorization_sha256, 64),
        (source_revision, 40),
        (manifest_sha256, 64),
    ):
        _exact_hash(value, size)
    if (
        not isinstance(authorization_ref, str)
        or not authorization_ref.strip()
        or len(authorization_ref) > 512
    ):
        raise ValueError('authorization reference is required')
    if set(expected_snapshot) != {'attempts', 'reserved_micro_usd', 'pending', 'stop_reason', 'state_sha256'}:
        raise ValueError('exact full expected snapshot required')
    _exact_hash(expected_snapshot['state_sha256'], 64)
    if any(type(expected_snapshot[key]) is not int for key in ('attempts', 'reserved_micro_usd', 'pending')):
        raise ValueError('snapshot integers must be exact')
    with evaluation_run_ownership(path), closing(sqlite3.connect(path, timeout=10)) as db, db:
        db.execute('PRAGMA synchronous=FULL')
        db.execute('BEGIN IMMEDIATE')
        if _followup_exists(db) or _final_format_exists(db):
            raise ValueError('evaluation followup already exists')
        _verified_first_extension(db, previous_audit_sha256)
        snapshot = _followup_snapshot(db)
        state = _historical_state(db)
        if snapshot != expected_snapshot or snapshot['pending']:
            raise ValueError('snapshot mismatch or pending usage blocks followup')
        active = db.execute(
            'SELECT s.rowid,s.reason FROM status s WHERE NOT EXISTS '
            '(SELECT 1 FROM gate_resolutions r WHERE r.status_rowid=s.rowid '
            'AND r.reason=s.reason) ORDER BY s.rowid'
        ).fetchall()
        resolved = 0
        if active:
            if (
                len(active) != 1
                or active[0][1] != 'budget_or_attempt_limit'
                or snapshot['attempts'] != 1100
                or snapshot['reserved_micro_usd'] + ATTEMPT_MICRO > 6000000
            ):
                raise ValueError('only an exact attempt-limit stop with remaining USD6 may be resolved')
            resolved = active[0][0]
            db.execute(
                'INSERT INTO gate_resolutions VALUES (?,?,?,?,?,?,?)',
                (
                    resolved,
                    'budget_or_attempt_limit',
                    source_revision,
                    authorization_sha256,
                    manifest_sha256,
                    snapshot['attempts'],
                    snapshot['reserved_micro_usd'],
                ),
            )
        # Seal the post-acknowledgment prefix; both inserts roll back together.
        sealed = _followup_snapshot(db)
        record = {
            'version': 2,
            'old_cap_micro': 6000000,
            'new_cap_micro': 6000000,
            'old_max_attempts': 1100,
            'new_max_attempts': 1600,
            'attempts': snapshot['attempts'],
            'reserved_micro_usd': snapshot['reserved_micro_usd'],
            'last_attempt_id': state['attempts'][-1][0],
            'last_status_rowid': state['status'][-1][0] if state['status'] else 0,
            'state_sha256': sealed['state_sha256'],
            'resolved_attempt_limit_status_rowid': resolved,
            'previous_audit_sha256': previous_audit_sha256,
            'authorization_ref': authorization_ref,
            'authorization_sha256': authorization_sha256,
            'source_revision': source_revision,
            'manifest_sha256': manifest_sha256,
            'created_at': datetime.now(UTC).isoformat(),
        }
        digest = _insert_followup(db, record)
        _verified_followup(db, digest)
    return digest


_FINAL_FORMAT_TABLE = 'authorized_envelope_final_format'
_FINAL_FORMAT_FIELDS = _EXTENSION_FIELDS | {'previous_audit_sha256', 'pending'}


def _final_format_exists(db: sqlite3.Connection) -> bool:
    return (
        db.execute(
            'SELECT 1 FROM sqlite_master WHERE type=? AND name=?', ('table', _FINAL_FORMAT_TABLE)
        ).fetchone()
        is not None
    )


def _final_format_state(
    db: sqlite3.Connection, *, attempt_id: int | None = None, status_rowid: int | None = None
) -> dict[str, Any]:
    return {
        'prior': _followup_state(db, attempt_id=attempt_id, status_rowid=status_rowid),
        'followup_event': db.execute(
            'SELECT id,record_json,record_sha256 FROM authorized_envelope_followup ORDER BY id'
        ).fetchall(),
    }


def _final_format_snapshot(db: sqlite3.Connection) -> dict[str, Any]:
    snapshot = _snapshot(db)
    snapshot['state_sha256'] = _state_hash(_final_format_state(db))
    return snapshot


def inspect_final_format_candidate(path: Path, *, previous_audit_sha256: str) -> dict[str, Any]:
    """Read-only candidate for the fixed third event; no key or allowance creation."""
    _exact_hash(previous_audit_sha256, 64)
    _private_existing_ledger(path)
    with (
        evaluation_run_ownership(path),
        closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)) as db,
    ):
        db.execute('BEGIN')
        if _final_format_exists(db):
            raise ValueError('final-format evaluation event already exists')
        if not _followup_exists(db):
            raise ValueError('no audited followup exists for final-format event')
        _verified_followup(db, previous_audit_sha256)
        return _final_format_snapshot(db)


def _verified_final_format(db: sqlite3.Connection, expected_sha256: str) -> dict[str, Any]:
    rows = db.execute('SELECT id,record_json,record_sha256 FROM authorized_envelope_final_format').fetchall()
    if len(rows) != 1 or rows[0][0] != 1:
        raise ValueError('invalid final-format audit cardinality')
    _, raw, digest = rows[0]
    if (
        not isinstance(raw, str)
        or hashlib.sha256(raw.encode()).hexdigest() != digest
        or digest != expected_sha256
    ):
        raise ValueError('final-format evaluation audit SHA256 mismatch')
    record = json.loads(raw)
    if not isinstance(record, dict) or set(record) != _FINAL_FORMAT_FIELDS or _canonical(record) != raw:
        raise ValueError('invalid final-format audit record')
    for key in (
        'version',
        'old_cap_micro',
        'old_max_attempts',
        'new_cap_micro',
        'new_max_attempts',
        'attempts',
        'reserved_micro_usd',
        'last_attempt_id',
        'last_status_rowid',
        'pending',
    ):
        if type(record[key]) is not int or record[key] < 0:
            raise ValueError('invalid final-format audit integers')
    if (
        record['version'] != 3
        or (record['old_max_attempts'], record['new_max_attempts']) != (1600, 2100)
        or (record['old_cap_micro'], record['new_cap_micro']) != (6000000, 6000000)
        or not 1 <= record['attempts'] <= 1600
        or record['reserved_micro_usd'] > 6000000
        or record['pending'] != 0
    ):
        raise ValueError('final-format event is outside the exact authorized transition')
    for key, size in (
        ('previous_audit_sha256', 64),
        ('state_sha256', 64),
        ('authorization_sha256', 64),
        ('source_revision', 40),
        ('manifest_sha256', 64),
    ):
        _exact_hash(record[key], size)
    if (
        not isinstance(record['authorization_ref'], str)
        or not record['authorization_ref'].strip()
        or len(record['authorization_ref']) > 512
        or not isinstance(record['created_at'], str)
    ):
        raise ValueError('final-format authorization reference and timestamp required')
    # Only this verified third event raises the effective current-count ceiling.
    # Prior event payloads, their exact historical limits and both prefix hashes stay intact.
    _verified_followup(db, record['previous_audit_sha256'], effective_max_attempts=2100)
    original = _final_format_state(
        db, attempt_id=record['last_attempt_id'], status_rowid=record['last_status_rowid']
    )
    attempts = original['prior']['legacy']['attempts']
    if (
        _state_hash(original) != record['state_sha256']
        or len(attempts) != record['attempts']
        or sum(row[1] for row in attempts) != record['reserved_micro_usd']
        or any(row[2] != 1 for row in attempts)
    ):
        raise ValueError('final-format historical prefix changed or contains pending usage')
    current = _snapshot(db)
    if (
        current['attempts'] < record['attempts']
        or current['attempts'] > 2100
        or current['reserved_micro_usd'] > 6000000
    ):
        raise ValueError('current accounting exceeds the final-format event')
    return record


def _insert_final_format(db: sqlite3.Connection, record: dict[str, Any]) -> str:
    raw = _canonical(record)
    digest = hashlib.sha256(raw.encode()).hexdigest()
    db.execute(
        'CREATE TABLE authorized_envelope_final_format (id INTEGER PRIMARY KEY CHECK(id=1), '
        'record_json TEXT NOT NULL, record_sha256 TEXT NOT NULL)'
    )
    db.execute('INSERT INTO authorized_envelope_final_format VALUES (1,?,?)', (raw, digest))
    return digest


def extend_evaluation_final_format(
    path: Path,
    *,
    previous_audit_sha256: str,
    expected_snapshot: dict[str, Any],
    authorization_ref: str,
    authorization_sha256: str,
    source_revision: str,
    manifest_sha256: str,
) -> str:
    """Fixed offline 1600→2100 event, same USD6; never edit counters, stops or prior events."""
    _private_existing_ledger(path)
    for value, size in (
        (previous_audit_sha256, 64),
        (authorization_sha256, 64),
        (source_revision, 40),
        (manifest_sha256, 64),
    ):
        _exact_hash(value, size)
    if (
        not isinstance(authorization_ref, str)
        or not authorization_ref.strip()
        or len(authorization_ref) > 512
    ):
        raise ValueError('authorization reference is required')
    if set(expected_snapshot) != {'attempts', 'reserved_micro_usd', 'pending', 'stop_reason', 'state_sha256'}:
        raise ValueError('exact full expected snapshot required')
    _exact_hash(expected_snapshot['state_sha256'], 64)
    if any(type(expected_snapshot[key]) is not int for key in ('attempts', 'reserved_micro_usd', 'pending')):
        raise ValueError('snapshot integers must be exact')
    with evaluation_run_ownership(path), closing(sqlite3.connect(path, timeout=10)) as db, db:
        db.execute('PRAGMA synchronous=FULL')
        db.execute('BEGIN IMMEDIATE')
        if _final_format_exists(db):
            raise ValueError('final-format evaluation event already exists')
        if not _followup_exists(db):
            raise ValueError('no audited followup exists for final-format event')
        _verified_followup(db, previous_audit_sha256)
        snapshot = _final_format_snapshot(db)
        if snapshot != expected_snapshot or snapshot['pending'] or snapshot['stop_reason']:
            raise ValueError('snapshot mismatch, pending usage or any stop blocks final-format event')
        state = _historical_state(db)
        record = {
            'version': 3,
            'old_cap_micro': 6000000,
            'new_cap_micro': 6000000,
            'old_max_attempts': 1600,
            'new_max_attempts': 2100,
            'attempts': snapshot['attempts'],
            'reserved_micro_usd': snapshot['reserved_micro_usd'],
            'pending': 0,
            'last_attempt_id': state['attempts'][-1][0],
            'last_status_rowid': state['status'][-1][0] if state['status'] else 0,
            'state_sha256': snapshot['state_sha256'],
            'previous_audit_sha256': previous_audit_sha256,
            'authorization_ref': authorization_ref,
            'authorization_sha256': authorization_sha256,
            'source_revision': source_revision,
            'manifest_sha256': manifest_sha256,
            'created_at': datetime.now(UTC).isoformat(),
        }
        digest = _insert_final_format(db, record)
        _verified_final_format(db, digest)
    return digest


@dataclass(slots=True)
class _EmbeddingReservation:
    attempt: int
    byte_bound: int
    known: bool = False
    unreported: bool = False


class EvaluationEmbeddingAccounting:
    """Both application accounting and the existing private envelope precede SDK I/O.

    Correlation is local to this sequential evaluation owner; durable costs and stops
    remain in the original ledgers. This helper neither reads a key nor dispatches work.
    """

    def __init__(self, application: EmbeddingAccounting, envelope: Envelope) -> None:
        self.application = application
        self.envelope = envelope
        self._operations: dict[str, _EmbeddingReservation] = {}
        self.receipts: list[dict[str, Any]] = []

    async def reserve(self, max_input_tokens: int, purpose: EmbeddingPurpose) -> str:
        if type(max_input_tokens) is not int or not 0 < max_input_tokens <= 240000:
            raise ValueError('embedding byte bound must be between one and 240000')
        if not isinstance(purpose, EmbeddingPurpose):
            raise TypeError('unknown embedding purpose')
        operation = await self.application.reserve(max_input_tokens, purpose)
        try:
            attempt = self.envelope.reserve()
        except Exception:
            await asyncio.shield(self.application.settle(operation, 0))
            raise
        if operation in self._operations:
            self.envelope.stop('duplicate_embedding_operation')
            raise ValueError('application embedding operation must be unique')
        self._operations[operation] = _EmbeddingReservation(attempt, max_input_tokens)
        self.receipts.append(
            {
                'attempt': attempt,
                'kind': 'embedding',
                'purpose': purpose.value,
                'input_byte_bound': max_input_tokens,
                'usage': None,
            }
        )
        return operation

    def _operation(self, operation: str) -> _EmbeddingReservation:
        try:
            return self._operations[operation]
        except KeyError:
            self.envelope.stop('unknown_embedding_operation')
            raise ValueError('unknown embedding evaluation operation') from None

    async def settle(self, operation_id: str, input_tokens: int) -> None:
        reservation = self._operation(operation_id)
        if not self.envelope.settle_embedding(
            reservation.attempt, input_tokens, input_byte_bound=reservation.byte_bound
        ):
            raise ValueError('embedding usage is invalid or already settled')
        reservation.known = True
        next(receipt for receipt in self.receipts if receipt['attempt'] == reservation.attempt)['usage'] = {
            'input': input_tokens
        }
        try:
            await self.application.settle(operation_id, input_tokens)
        except BaseException:
            self.envelope.stop('embedding_application_accounting_failure')
            await asyncio.shield(self.application.mark_unreported(operation_id))
            raise

    async def mark_unreported(self, operation_id: str) -> None:
        reservation = self._operation(operation_id)
        # OpenAIEmbeddings calls this after a malformed vector even when usage was
        # already settled. That must neither refund nor settle the same request twice.
        if reservation.known or reservation.unreported:
            return
        reservation.unreported = True
        try:
            await asyncio.shield(self.application.mark_unreported(operation_id))
        finally:
            self.envelope.stop('missing_embedding_usage')


def bound_bytes(request: ModelRequest) -> int:
    return request.size_bytes()


class BoundedProvider:
    def __init__(
        self, key: str, envelope: Envelope, *, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self._key = key
        self.envelope = envelope
        self.transport = transport
        self.receipts: list[dict[str, Any]] = []

    @property
    def model(self) -> str:
        return MODEL

    async def stream(self, request: ModelRequest) -> AsyncGenerator[ModelChunk]:
        byte_bound = bound_bytes(request)
        if not 0 < request.max_output_tokens <= 4000 or byte_bound > 24000:
            self.envelope.stop('request_bound')
            raise RejectedError(FailureCode.INVALID_REQUEST)
        attempt = self.envelope.reserve()
        receipt: dict[str, Any] = {'attempt': attempt, 'input_byte_bound': byte_bound, 'usage': None}
        self.receipts.append(receipt)

        async def check_wire(wire: httpx.Request) -> None:
            if len(wire.content) > 24000:
                self.envelope.stop('wire_bound')
                raise RejectedError(FailureCode.INVALID_REQUEST)

        # Explicit URL, no proxy/environment trust, standard tier, no SDK or adapter retries.
        async with (
            httpx.AsyncClient(
                transport=self.transport, trust_env=False, timeout=30, event_hooks={'request': [check_wire]}
            ) as http,
            AsyncOpenAI(
                api_key=self._key,
                base_url='https://api.openai.com/v1',
                http_client=http,
                timeout=30,
                max_retries=0,
            ) as client,
        ):
            provider = OpenAIResponsesProvider(client, MODEL, 'medium', 0)
            try:
                async for chunk in provider.stream(request):
                    if isinstance(chunk, UsageChunk):
                        usage = chunk.usage
                        receipt['usage'] = {
                            'input': usage.input_tokens,
                            'output': usage.output_tokens,
                            'cached': usage.cached_input_tokens,
                            'cache_write': usage.cache_write_tokens,
                            'reasoning': usage.reasoning_tokens,
                        }
                        self.envelope.settle(attempt, usage.input_tokens, usage.output_tokens)
                    yield chunk
            except RejectedError as error:
                # The adapter chains original SDK errors without exposing bodies/keys.
                cause = error.__cause__
                if isinstance(
                    cause,
                    (
                        openai.AuthenticationError,
                        openai.PermissionDeniedError,
                        openai.NotFoundError,
                        openai.BadRequestError,
                    ),
                ):
                    self.envelope.stop(type(cause).__name__)
                raise
