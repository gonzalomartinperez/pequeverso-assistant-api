"""Real PG import of synthetic closed SQLite snapshots, preserving the original file."""

import asyncio
import hashlib
from datetime import timedelta
from pathlib import Path

import psycopg
import pytest

from app.adapters.postgres import import_sqlite as importer
from app.adapters.postgres.import_sqlite import import_snapshot
from app.adapters.postgres.private_ledger import PostgresLedger
from app.adapters.postgres.private_stores import PostgresMessageStore, PostgresRunStore, PostgresSessionStore
from app.adapters.sqlite.catalog_repository import SqliteCatalogRepository
from app.adapters.sqlite.database import Database
from app.adapters.sqlite.ledger import SqliteLedger
from app.adapters.sqlite.stores import SqliteMessageStore, SqliteRunStore, SqliteSessionStore
from app.application.ports import RunState
from app.domain.budget import Usage
from app.domain.conversation import Message, Role
from tests.support import CATALOG_BYTES
from tests.test_postgres_knowledge import DSN, PARSE
from tests.test_postgres_private import NOW, private_database, session

pytestmark = pytest.mark.skipif(not DSN, reason='requires explicitly isolated real PG18.6')


async def legacy_snapshot(path: Path, *, invalid_run_reference: bool = False) -> None:
    db = Database(str(path))
    await db.open()
    try:
        await SqliteSessionStore(db).create(session('legacy-session'), b'fixture-import-digest')
        messages = SqliteMessageStore(db)
        await messages.append(
            'legacy-session', Message('legacy-user', Role.USER, 'Authored synthetic question', NOW)
        )
        await messages.append(
            'legacy-session', Message('legacy-answer', Role.ASSISTANT, 'Authored synthetic answer', NOW)
        )
        runs = SqliteRunStore(db)
        await runs.claim('legacy-run', 'legacy-session', 'legacy-key', 'request-fingerprint', NOW)
        await runs.finish(
            'legacy-run', RunState.COMPLETED, 'missing-answer' if invalid_run_reference else 'legacy-answer'
        )
        ledger = SqliteLedger(db)
        for id_ in ['legacy-run', 'unknown-query', 'embedding:index:fixture']:
            assert await ledger.reserve(id_, 100, '2026-10', '2026-10-17', lambda **_: True)
        await ledger.settle(
            'legacy-run', 40, Usage(10, 3, cached_input_tokens=2, reasoning_tokens=1), 'fixture'
        )
        await ledger.mark_unreported('unknown-query')
        await SqliteCatalogRepository(db).activate(
            hashlib.sha256(CATALOG_BYTES).hexdigest(), CATALOG_BYTES, PARSE(CATALOG_BYTES), NOW, NOW
        )
    finally:
        await db.close()


async def private_counts(db: object) -> tuple[int, int, int]:
    # The helper uses the concrete test database only; no polymorphic production API is added.
    from app.adapters.postgres.database import PostgresDatabase

    assert isinstance(db, PostgresDatabase)
    async with db.pool.connection() as conn:
        row = await (
            await conn.execute(
                'SELECT (SELECT count(*) FROM assistant_private.sessions) AS sessions,'
                '(SELECT count(*) FROM assistant_private.spend_ledger) AS ledger,'
                '(SELECT count(*) FROM assistant_private.sqlite_imports) AS imports',
            )
        ).fetchone()
    assert row is not None
    return int(row['sessions']), int(row['ledger']), int(row['imports'])


def test_full_import_keeps_hash_csrf_history_replay_tokens_unknown_spend_and_public_separation(
    tmp_path: Path,
) -> None:
    async def run() -> None:
        path = tmp_path / 'legacy.sqlite3'
        await legacy_snapshot(path)
        original = path.read_bytes()
        async with private_database() as db:
            receipt = await import_snapshot(db, path, source_quiescent=True)
            assert not receipt.already_imported
            assert (
                receipt.counts['sessions'] == 1
                and receipt.counts['messages'] == 2
                and receipt.counts['spend_ledger'] == 3
            )
            assert (await import_snapshot(db, path, source_quiescent=True)).already_imported
            assert await PostgresSessionStore(db).find(b'fixture-import-digest', NOW) == session(
                'legacy-session'
            )
            history = await PostgresMessageStore(db).history('legacy-session', 20)
            assert [m.content for m in history] == [
                'Authored synthetic question',
                'Authored synthetic answer',
            ]
            replay = await PostgresRunStore(db).claim(
                'ignored', 'legacy-session', 'legacy-key', 'request-fingerprint', NOW
            )
            assert replay.state is RunState.COMPLETED and replay.assistant_message_id == 'legacy-answer'
            assert await PostgresLedger(db).spent('2026-10', '2026-10-17') == (240, 240)
            async with db.pool.connection() as conn:
                row = await (
                    await conn.execute(
                        "SELECT input_tokens,output_tokens,cached_input_tokens,reasoning_tokens FROM assistant_private.spend_ledger WHERE run_id='legacy-run'"
                    )
                ).fetchone()
                assert row is not None and tuple(row.values()) == (10, 3, 2, 1)
                public = await (
                    await conn.execute('SELECT count(*) AS n FROM knowledge.revisions')
                ).fetchone()
                assert public is not None and public['n'] == 0
            await PostgresMessageStore(db).append(
                'legacy-session',
                Message('after-import', Role.USER, 'New authored turn', NOW + timedelta(seconds=1)),
            )
            assert [m.id for m in await PostgresMessageStore(db).history('legacy-session', 20)] == [
                'legacy-user',
                'legacy-answer',
                'after-import',
            ]
            with pytest.raises(ValueError, match='target data no longer matches'):
                await import_snapshot(db, path, source_quiescent=True)
        assert path.read_bytes() == original

    asyncio.run(run())


def test_import_refuses_partial_existing_target_without_deleting_anything(tmp_path: Path) -> None:
    async def run() -> None:
        path = tmp_path / 'legacy.sqlite3'
        await legacy_snapshot(path)
        async with private_database() as db:
            await PostgresSessionStore(db).create(session('existing-target'), b'existing-digest')
            with pytest.raises(ValueError, match='empty private target'):
                await import_snapshot(db, path, source_quiescent=True)
            assert await private_counts(db) == (1, 0, 0)
            assert await PostgresSessionStore(db).find(b'existing-digest', NOW) == session('existing-target')

    asyncio.run(run())


def test_mid_transaction_constraint_failure_rolls_back_every_imported_table(tmp_path: Path) -> None:
    async def run() -> None:
        path = tmp_path / 'invalid-run.sqlite3'
        # SQLite's released run table has no assistant-message FK; the PG adapter strengthens it.
        await legacy_snapshot(path, invalid_run_reference=True)
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        async with private_database() as db:
            with pytest.raises(psycopg.errors.ForeignKeyViolation):
                await import_snapshot(db, path, source_quiescent=True)
            assert await private_counts(db) == (0, 0, 0)
        assert hashlib.sha256(path.read_bytes()).hexdigest() == before

    asyncio.run(run())


def test_source_change_before_commit_rolls_back_real_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def run() -> None:
        path = tmp_path / 'changing-source.sqlite3'
        await legacy_snapshot(path)
        original = importer._source_hash
        calls = 0

        def changed(source: Path) -> str:
            nonlocal calls
            calls += 1
            return 'f' * 64 if calls >= 3 else original(source)

        monkeypatch.setattr(importer, '_source_hash', changed)
        async with private_database() as db:
            with pytest.raises(ValueError, match='source changed before commit'):
                await import_snapshot(db, path, source_quiescent=True)
            assert await private_counts(db) == (0, 0, 0)

    asyncio.run(run())


def test_missing_quiescence_and_journal_companions_refuse_before_any_target_mutation(tmp_path: Path) -> None:
    async def run() -> None:
        path = tmp_path / 'open-source.sqlite3'
        await legacy_snapshot(path)
        async with private_database() as db:
            with pytest.raises(ValueError, match='quiescent attestation'):
                await import_snapshot(db, path, source_quiescent=False)
            await asyncio.to_thread(Path(str(path) + '-wal').write_bytes, b'synthetic-active-wal')
            with pytest.raises(ValueError, match='journal companions'):
                await import_snapshot(db, path, source_quiescent=True)
            assert await private_counts(db) == (0, 0, 0)

    asyncio.run(run())
