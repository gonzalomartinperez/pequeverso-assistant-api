"""Explicit one-shot import of an attested, closed SQLite snapshot; never a startup action.

Source is read-only and remains intact. One target transaction locks private tables, validates
an empty/idempotent target, inserts and reconciles canonical counts/hashes before commit.
Legacy public catalog bytes are archived, never activated or embedded by this migration.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from psycopg import AsyncConnection, sql
from psycopg.types.json import Jsonb

from app.adapters.postgres.database import PostgresDatabase, Row

# Source columns are frozen to the released SQLite schema version2, not inferred from data.
TABLES: dict[str, tuple[str, ...]] = {
    'sessions': ('id', 'secret_digest', 'csrf_token', 'created_at', 'last_active_at', 'expires_at'),
    'messages': ('seq', 'id', 'session_id', 'role', 'content', 'details', 'created_at'),
    'runs': (
        'id',
        'session_id',
        'idempotency_key',
        'request_hash',
        'state',
        'assistant_message_id',
        'created_at',
    ),
    'spend_ledger': (
        'run_id',
        'month',
        'day',
        'reserved_micro',
        'actual_micro',
        'model',
        'input_tokens',
        'output_tokens',
        'cached_input_tokens',
        'created_at',
        'status',
        'reasoning_tokens',
        'settled_at',
    ),
    'rate_counters': ('key', 'window_start', 'count'),
    'run_metrics': (
        'run_id',
        'started_at',
        'ended_at',
        'day',
        'outcome',
        'code',
        'model_call',
        'replaced',
        'language',
        'first_delta_ms',
        'total_ms',
    ),
    'catalog_snapshots': (
        'sha256',
        'schema_version',
        'source_revision',
        'generated_at',
        'activated_at',
        'body',
    ),
    'catalog_state': (
        'id',
        'active_sha256',
        'verified_at',
        'last_attempt_at',
        'last_failure',
        'last_failure_at',
    ),
}
TARGETS = {name: ('legacy_' + name if name.startswith('catalog_') else name) for name in TABLES}
ORDER = {'messages': ('seq',), 'rate_counters': ('key', 'window_start')}
TIMESTAMPS = frozenset(
    {
        'created_at',
        'last_active_at',
        'expires_at',
        'started_at',
        'ended_at',
        'settled_at',
        'generated_at',
        'activated_at',
        'verified_at',
        'last_attempt_at',
        'last_failure_at',
    }
)
MAX_SNAPSHOT_BYTES = 64 * 1024 * 1024
MAX_SNAPSHOT_ROWS = 250_000


@dataclass(frozen=True, slots=True)
class ImportReceipt:
    source_sha256: str
    canonical_sha256: str
    counts: dict[str, int]
    source_schema_version: int = 2
    already_imported: bool = False


@dataclass(frozen=True, slots=True)
class _Snapshot:
    source_sha256: str
    canonical_sha256: str
    tables: dict[str, list[tuple[Any, ...]]]


def _source_hash(path: Path) -> str:
    if any(Path(str(path) + suffix).exists() for suffix in ('-wal', '-shm', '-journal')):
        raise ValueError('source must be a closed standalone SQLite snapshot without journal companions')
    if not path.is_file() or path.stat().st_size > MAX_SNAPSHOT_BYTES:
        raise ValueError('snapshot is absent or exceeds the explicitly bounded import size')
    digest = hashlib.sha256()
    with path.open('rb') as source:
        while block := source.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _value(column: str, value: Any) -> Any:
    if value is None:
        return None
    if column in TIMESTAMPS:
        parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
        if not isinstance(parsed, datetime) or parsed.tzinfo is None:
            raise ValueError('legacy timestamps must retain an explicit timezone')
        return parsed.astimezone(UTC)
    if column in ('model_call', 'replaced'):
        if value not in (False, True, 0, 1):
            raise ValueError('legacy boolean is invalid')
        return bool(value)
    return bytes(value) if isinstance(value, memoryview) else value


def _json_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat(timespec='microseconds')
    if isinstance(value, bytes):
        return {'bytes': value.hex()}
    return value


def _canonical(tables: dict[str, list[tuple[Any, ...]]]) -> str:
    digest = hashlib.sha256()
    for name, columns in TABLES.items():
        digest.update(json.dumps([name, columns], separators=(',', ':')).encode())
        for row in tables[name]:
            digest.update(
                json.dumps(
                    [_json_value(v) for v in row], ensure_ascii=False, separators=(',', ':'), allow_nan=False
                ).encode()
            )
            digest.update(b'\n')
    return digest.hexdigest()


def _read_snapshot(path: Path) -> _Snapshot:
    if path.is_symlink():
        raise ValueError('snapshot must be an explicit regular file, not a symlink')
    before = _source_hash(path)
    tables: dict[str, list[tuple[Any, ...]]] = {}
    # A closed WAL-mode database can create sidecars even with mode=ro. Only this explicitly
    # attested standalone snapshot uses immutable=1; before/after hashes and absent journals
    # are mandatory, so an active WAL source is never silently read without its changes.
    connection = sqlite3.connect(path.resolve().as_uri() + '?mode=ro&immutable=1', uri=True)
    try:
        connection.execute('PRAGMA query_only=ON')
        connection.execute('PRAGMA trusted_schema=OFF')
        connection.execute('BEGIN')
        if connection.execute('PRAGMA user_version').fetchone()[0] != 2:
            raise ValueError('import requires a validated SQLite schema version2 snapshot')
        if (
            connection.execute('PRAGMA quick_check').fetchone()[0] != 'ok'
            or connection.execute('PRAGMA foreign_key_check').fetchone()
        ):
            raise ValueError('SQLite source integrity check failed')
        actual = {
            r[0]
            for r in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        if actual != set(TABLES):
            raise ValueError('SQLite source inventory does not match the released schema')
        total = 0
        for name, columns in TABLES.items():
            actual_columns = {
                r[0] for r in connection.execute('SELECT name FROM pragma_table_info(?)', (name,))
            }
            if actual_columns != set(columns):
                raise ValueError('SQLite source columns do not match the released schema')
            # Identifiers come solely from the frozen inventory above, never snapshot/user text.
            query = (
                sql.SQL('SELECT {} FROM {} ORDER BY {}')
                .format(
                    sql.SQL(',').join(map(sql.Identifier, columns)),
                    sql.Identifier(name),
                    sql.SQL(',').join(map(sql.Identifier, ORDER.get(name, (columns[0],)))),
                )
                .as_string()
            )
            rows = connection.execute(query).fetchall()
            total += len(rows)
            if total > MAX_SNAPSHOT_ROWS:
                raise ValueError('SQLite source exceeds the explicit import row bound')
            tables[name] = [
                tuple(_value(column, value) for column, value in zip(columns, row, strict=True))
                for row in rows
            ]
        connection.rollback()
    finally:
        connection.close()
    if _source_hash(path) != before:
        raise ValueError('SQLite snapshot changed while being read; stop the source writer')
    return _Snapshot(before, _canonical(tables), tables)


async def _target_rows(conn: AsyncConnection[Row]) -> dict[str, list[tuple[Any, ...]]]:
    result: dict[str, list[tuple[Any, ...]]] = {}
    for source, columns in TABLES.items():
        query = sql.SQL('SELECT {} FROM {} ORDER BY {}').format(
            sql.SQL(',').join(map(sql.Identifier, columns)),
            sql.Identifier('assistant_private', TARGETS[source]),
            sql.SQL(',').join(map(sql.Identifier, ORDER.get(source, (columns[0],)))),
        )
        rows = await (await conn.execute(query)).fetchall()
        result[source] = [tuple(_value(column, row[column]) for column in columns) for row in rows]
    return result


async def import_snapshot(
    db: PostgresDatabase,
    path: Path,
    *,
    source_quiescent: bool,
) -> ImportReceipt:
    if not source_quiescent:
        raise ValueError('explicit source-quiescent attestation is required')
    snapshot = await asyncio.to_thread(_read_snapshot, path)
    counts = {name: len(rows) for name, rows in snapshot.tables.items()}
    async with db.pool.connection() as conn:
        await conn.execute('SELECT pg_advisory_xact_lock(684721026)')
        await conn.execute('SELECT pg_advisory_xact_lock(684721025)')
        await conn.execute(
            sql.SQL('LOCK TABLE {} IN ACCESS EXCLUSIVE MODE').format(
                sql.SQL(',').join(sql.Identifier('assistant_private', target) for target in TARGETS.values()),
            )
        )
        imports = await (
            await conn.execute(
                'SELECT source_sha256,canonical_sha256,counts FROM assistant_private.sqlite_imports'
            )
        ).fetchall()
        if imports:
            if len(imports) != 1 or imports[0]['source_sha256'] != snapshot.source_sha256:
                raise ValueError('target already contains an import from a different snapshot')
            target = await _target_rows(conn)
            if (
                _canonical(target) != snapshot.canonical_sha256
                or imports[0]['canonical_sha256'] != snapshot.canonical_sha256
                or imports[0]['counts'] != counts
            ):
                raise ValueError('idempotent import refused: target data no longer matches the snapshot')
            return ImportReceipt(
                snapshot.source_sha256, snapshot.canonical_sha256, counts, already_imported=True
            )
        if any((await _target_rows(conn)).values()):
            raise ValueError('import requires an empty private target; partial/existing data is preserved')
        for source, columns in TABLES.items():
            query = sql.SQL('INSERT INTO {}({}) VALUES({})').format(
                sql.Identifier('assistant_private', TARGETS[source]),
                sql.SQL(',').join(map(sql.Identifier, columns)),
                sql.SQL(',').join(sql.Placeholder() for _ in columns),
            )
            async with conn.cursor() as cursor:
                rows = snapshot.tables[source]
                for offset in range(0, len(rows), 500):
                    await cursor.executemany(query, rows[offset : offset + 500])
        target = await _target_rows(conn)
        if {name: len(rows) for name, rows in target.items()} != counts or _canonical(
            target
        ) != snapshot.canonical_sha256:
            raise ValueError('import reconciliation failed; target transaction rolled back')
        if await asyncio.to_thread(_source_hash, path) != snapshot.source_sha256:
            raise ValueError('source changed before commit; target transaction rolled back')
        await conn.execute(
            "SELECT setval(pg_get_serial_sequence('assistant_private.messages','seq'),"
            'coalesce(max(seq),1),count(*)>0) FROM assistant_private.messages',
        )
        await conn.execute(
            'INSERT INTO assistant_private.sqlite_imports(source_sha256,canonical_sha256,source_schema_version,counts)'
            ' VALUES(%s,%s,2,%s)',
            (snapshot.source_sha256, snapshot.canonical_sha256, Jsonb(counts)),
        )
    return ImportReceipt(snapshot.source_sha256, snapshot.canonical_sha256, counts)
