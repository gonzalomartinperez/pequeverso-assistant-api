"""Offline snapshot validation and reconciliation with an in-memory target double."""

import asyncio
import sqlite3
from contextlib import asynccontextmanager, closing
from copy import deepcopy
from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock

import pytest

from app.adapters.postgres import import_sqlite
from tests.test_postgres_import import legacy_snapshot


@pytest.fixture
def snapshot(tmp_path):
    path = tmp_path / "fixture.sqlite"
    asyncio.run(legacy_snapshot(path))
    return path


@pytest.mark.parametrize(
    ("problem", "message"),
    [
        ("unattested", "quiescent attestation"),
        ("symlink", "not a symlink"),
        ("journal", "journal companions"),
        ("missing", "absent or exceeds"),
        ("size", "absent or exceeds"),
        ("version", "schema version2"),
        ("inventory", "inventory does not match"),
        ("columns", "columns do not match"),
        ("row_limit", "row bound"),
        ("naive_time", "explicit timezone"),
    ],
)
def test_invalid_source_is_rejected_before_target_access(snapshot, monkeypatch, problem, message):
    db = Mock(pool=Mock())
    if problem == "symlink":
        link = snapshot.with_name("linked.sqlite")
        link.symlink_to(snapshot)
        snapshot = link
    elif problem == "journal":
        snapshot.with_suffix(".sqlite-wal").write_bytes(b"synthetic WAL")
    elif problem == "missing":
        snapshot.unlink()
    elif problem == "size":
        monkeypatch.setattr(import_sqlite, "MAX_SNAPSHOT_BYTES", 1)
    elif problem == "row_limit":
        monkeypatch.setattr(import_sqlite, "MAX_SNAPSHOT_ROWS", 0)
    else:
        statements = {
            "version": "PRAGMA user_version = 1",
            "inventory": "CREATE TABLE stray (id INTEGER)",
            "columns": "ALTER TABLE sessions ADD COLUMN stray TEXT",
            "naive_time": "UPDATE sessions SET created_at = '2026-10-17T12:00:00'",
        }
        if problem in statements:
            with closing(sqlite3.connect(snapshot)) as connection, connection:
                connection.execute(statements[problem])

    with pytest.raises(ValueError, match=message):
        asyncio.run(
            import_sqlite.import_snapshot(db, snapshot, source_quiescent=problem != "unattested")
        )
    db.pool.connection.assert_not_called()


class ImportTarget:
    """Emulate the private target's transaction and row round-trip without a driver."""

    def __init__(self, *, drop_message=False):
        self.rows = {target: [] for target in import_sqlite.TARGETS.values()}
        self.imports = []
        self.pool = self
        self.drop_message = drop_message
        self.sequence_reset = False

    @asynccontextmanager
    async def connection(self):
        original = deepcopy((self.rows, self.imports, self.sequence_reset))
        try:
            yield self
        except Exception:
            self.rows, self.imports, self.sequence_reset = original
            raise

    @asynccontextmanager
    async def cursor(self):
        yield self

    async def execute(self, query, values=None):
        statement = query if isinstance(query, str) else query.as_string()
        if statement.startswith(("SELECT pg_advisory_xact_lock(", "LOCK TABLE ")):
            return None
        if statement.startswith("SELECT setval("):
            self.sequence_reset = True
            return None
        if statement.startswith("INSERT INTO assistant_private.sqlite_imports("):
            source, canonical, counts = values
            self.imports.append(
                {"source_sha256": source, "canonical_sha256": canonical, "counts": counts.obj}
            )
            return None
        if "FROM assistant_private.sqlite_imports" in statement:
            rows = self.imports
        else:
            target = statement.split('FROM "assistant_private"."', 1)[1].split('"', 1)[0]
            rows = self.rows[target]
        return Mock(fetchall=AsyncMock(return_value=deepcopy(rows)))

    async def executemany(self, query, rows):
        statement = query.as_string()
        target, names = statement.split('INSERT INTO "assistant_private"."', 1)[1].split('"(', 1)
        names = names.split(")", 1)[0].replace('"', "").split(",")
        if self.drop_message and target == "messages":
            rows = rows[1:]
        self.rows[target].extend(dict(zip(names, row, strict=True)) for row in rows)


def test_snapshot_preserves_history_and_replays_only_against_the_same_target(snapshot):
    target = ImportTarget()
    original = snapshot.read_bytes()

    first = asyncio.run(import_sqlite.import_snapshot(target, snapshot, source_quiescent=True))
    assert first.counts["messages"] == 2
    assert first.counts["sessions"] == 1
    assert first.counts["spend_ledger"] == 3
    assert first.already_imported is False
    assert target.sequence_reset
    assert [row["id"] for row in target.rows["messages"]] == ["legacy-user", "legacy-answer"]
    assert target.rows["sessions"][0]["secret_digest"] == b"fixture-import-digest"
    assert isinstance(target.rows["sessions"][0]["created_at"], datetime)
    assert target.rows["sessions"][0]["created_at"].tzinfo is UTC
    assert len(target.rows["legacy_catalog_snapshots"]) == 1
    assert snapshot.read_bytes() == original

    repeat = asyncio.run(import_sqlite.import_snapshot(target, snapshot, source_quiescent=True))
    assert repeat.already_imported
    assert repeat.canonical_sha256 == first.canonical_sha256
    assert len(target.imports) == 1

    target.imports[0]["counts"] = {"messages": 9}
    with pytest.raises(ValueError, match="idempotent import refused"):
        asyncio.run(import_sqlite.import_snapshot(target, snapshot, source_quiescent=True))
    assert len(target.rows["messages"]) == 2


def test_insert_readback_mismatch_prevents_import_commit(snapshot):
    target = ImportTarget(drop_message=True)
    original = snapshot.read_bytes()

    with pytest.raises(ValueError, match="import reconciliation failed"):
        asyncio.run(import_sqlite.import_snapshot(target, snapshot, source_quiescent=True))

    assert not target.imports
    assert all(not rows for rows in target.rows.values())
    assert not target.sequence_reset
    assert snapshot.read_bytes() == original
