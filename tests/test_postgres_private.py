"""Private PG protocols against a real disposable database; no provider or customer data."""

import asyncio
import hashlib
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict

from app.adapters.postgres.database import PostgresDatabase
from app.adapters.postgres.private_ledger import PostgresLedger, PostgresRateLimiter
from app.adapters.postgres.private_operations import PostgresOperationsQueries, PostgresRunMetrics
from app.adapters.postgres.private_stores import PostgresMessageStore, PostgresRunStore, PostgresSessionStore
from app.application.ports import RunMetric, RunOutcome, RunState
from app.domain.budget import Usage
from app.domain.conversation import Message, Role, Session
from app.domain.errors import RejectedError
from app.domain.language import Language
from tests.test_postgres_knowledge import DSN

pytestmark = pytest.mark.skipif(not DSN, reason='requires explicitly isolated real PG18.6')
NOW = datetime(2026, 10, 17, 12, tzinfo=UTC)


@asynccontextmanager
async def private_database() -> AsyncIterator[PostgresDatabase]:
    assert DSN is not None
    info = conninfo_to_dict(DSN)
    if (
        info.get('host') != '127.0.0.1'
        or info.get('port') != '55439'
        or info.get('dbname') != 'pv_knowledge_test'
    ):
        raise ValueError('private test cleanup requires the isolated local database')
    db = PostgresDatabase(DSN)
    await db.open()
    try:
        async with db.pool.connection() as conn:
            await conn.execute('DROP SCHEMA IF EXISTS assistant_private CASCADE')
            await conn.execute('DROP SCHEMA IF EXISTS knowledge CASCADE')
        await db.migrate()
        await db.migrate()
        yield db
    finally:
        await db.close()


def session(id_: str) -> Session:
    return Session(id_, f'fixture-csrf-{id_}', NOW, NOW, NOW + timedelta(days=1))


def test_private_sessions_history_idempotency_isolation_and_cascade() -> None:
    async def run() -> None:
        async with private_database() as db:
            sessions = PostgresSessionStore(db)
            messages = PostgresMessageStore(db)
            runs = PostgresRunStore(db)
            first, other = session('one'), session('two')
            for value in (first, other):
                await sessions.create(value, hashlib.sha256(value.id.encode()).digest())
            assert await sessions.find(hashlib.sha256(first.id.encode()).digest(), NOW) == first
            assert await sessions.find(b'foreign-secret-digest', NOW) is None
            await messages.append('one', Message('user1', Role.USER, 'Synthetic private question', NOW))
            await messages.append('one', Message('assistant1', Role.ASSISTANT, 'Synthetic saved answer', NOW))
            assert [m.id for m in await messages.history('one', 20)] == ['user1', 'assistant1']
            assert await messages.history('two', 20) == []
            claimed = await asyncio.gather(
                *(runs.claim(f'r{i}', 'one', 'same-key', 'same-hash', NOW) for i in range(4))
            )
            assert len({r.id for r in claimed}) == 1
            assert await runs.message('two', 'assistant1') is None
            with pytest.raises(RejectedError):
                await runs.claim('different-key', 'one', 'other-key', 'other-hash', NOW)
            await runs.finish(claimed[0].id, RunState.COMPLETED, 'assistant1')
            replay = await runs.claim('ignored', 'one', 'same-key', 'same-hash', NOW)
            assert replay.state is RunState.COMPLETED and replay.assistant_message_id == 'assistant1'
            await runs.claim('run-two', 'two', 'key-two', 'hash-two', NOW)
            with pytest.raises(psycopg.errors.ForeignKeyViolation):
                await runs.finish('run-two', RunState.COMPLETED, 'assistant1')
            await sessions.delete('one')
            assert await messages.history('one', 20) == []
            assert await runs.message('one', 'assistant1') is None
            await sessions.touch('two', NOW, NOW - timedelta(seconds=1))
            assert await sessions.purge_expired(NOW) == 1
            assert await sessions.find(hashlib.sha256(other.id.encode()).digest(), NOW) is None

    asyncio.run(run())


def test_atomic_budget_across_independent_pools_and_embedding_generation_purposes() -> None:
    async def run() -> None:
        async with private_database() as db:
            assert DSN is not None
            other = PostgresDatabase(DSN)
            await other.open()
            try:
                ledgers = (PostgresLedger(db), PostgresLedger(other))

                def allows(*, month_spent: int, day_spent: int, reservation: int) -> bool:
                    return month_spent + reservation <= 100 and day_spent + reservation <= 100

                accepted = await asyncio.gather(
                    *(
                        ledgers[i % 2].reserve(
                            f'{"embedding:index" if i % 3 == 0 else "generation"}:{i}',
                            30,
                            '2026-10',
                            '2026-10-17',
                            allows,
                        )
                        for i in range(20)
                    )
                )
                assert sum(accepted) == 3
                assert await ledgers[0].spent('2026-10', '2026-10-17') == (90, 90)
            finally:
                await other.close()

    asyncio.run(run())


def test_unknown_usage_late_settlement_recovery_and_cost_survive_session_delete() -> None:
    async def run() -> None:
        async with private_database() as db:
            ledger = PostgresLedger(db)
            for id_ in ['generation', 'embedding:query:fixture', 'embedding:index:fixture']:
                assert await ledger.reserve(id_, 100, '2026-10', '2026-10-17', lambda **_: True)
            assert await ledger.abandon_pending() == 2
            async with db.pool.connection() as conn:
                row = await (
                    await conn.execute(
                        "SELECT status FROM assistant_private.spend_ledger WHERE run_id='embedding:index:fixture'"
                    )
                ).fetchone()
                assert row is not None and row['status'] == 'pending'
            assert await ledger.abandon_index_pending() == 1
            await ledger.settle(
                'generation',
                40,
                Usage(10, 2, cached_input_tokens=3, cache_write_tokens=1, reasoning_tokens=1),
                'fixture',
            )
            await ledger.mark_unreported('generation')
            await ledger.settle('embedding:index:fixture', 5, Usage(5, 0), 'text-embedding-3-small')
            with pytest.raises(LookupError, match='no open reservation'):
                await ledger.settle('generation', 0, Usage(0, 0), 'fixture')
            sessions = PostgresSessionStore(db)
            await sessions.create(session('deleted'), b'fixture-digest')
            await sessions.delete('deleted')
            assert await ledger.spent('2026-10', '2026-10-17') == (145, 145)
            async with db.pool.connection() as conn:
                row = await (
                    await conn.execute(
                        "SELECT status,cache_write_tokens FROM assistant_private.spend_ledger WHERE run_id='generation'"
                    )
                ).fetchone()
                assert row is not None and row['status'] == 'settled' and row['cache_write_tokens'] == 1

    asyncio.run(run())


def test_rate_counter_concurrency_recovery_and_expiry() -> None:
    async def run() -> None:
        async with private_database() as db:
            rates = PostgresRateLimiter(db)
            assert sum(await asyncio.gather(*(rates.hit('opaque-key', 60, 5, NOW) for _ in range(12)))) == 5
            assert await rates.hit('different-opaque-key', 60, 5, NOW)
            assert await rates.purge(NOW + timedelta(days=2), timedelta(days=1)) == 2
            sessions = PostgresSessionStore(db)
            await sessions.create(session('left-active'), b'active-fixture-digest')
            runs = PostgresRunStore(db)
            await runs.claim('abandoned', 'left-active', 'idempotent', 'request-hash', NOW)
            assert await runs.abandon_active() == 1
            assert (
                await runs.claim('ignored', 'left-active', 'idempotent', 'request-hash', NOW)
            ).state is RunState.FAILED

    asyncio.run(run())


def test_private_operations_are_content_free_and_match_existing_contract_semantics() -> None:
    async def run() -> None:
        async with private_database() as db:
            ledger = PostgresLedger(db)
            assert await ledger.reserve('opaque-run', 100, '2026-10', '2026-10-17', lambda **_: True)
            await ledger.settle(
                'opaque-run', 25, Usage(20, 4, cached_input_tokens=3, reasoning_tokens=1), 'fixture'
            )
            metrics = PostgresRunMetrics(db)
            metric = RunMetric(
                'opaque-run',
                NOW,
                NOW + timedelta(seconds=1),
                RunOutcome.COMPLETED,
                None,
                True,
                False,
                Language.ES,
                7,
                1000,
            )
            await metrics.record(metric)
            await metrics.record(metric)
            ops = PostgresOperationsQueries(db, db)
            assert (await ops.spend('month', '2026-10')).confirmed == 25
            assert (await ops.tokens(NOW)).input == 20
            window = await ops.run_window(NOW)
            assert window.counts['completed'] == 1 and window.first_delta_ms == [7]
            assert (await ops.daily('2026-10-17'))[0].tokens.output == 4
            recent = await ops.recent(50)
            assert len(recent) == 1 and recent[0].id == hashlib.sha256(b'opaque-run').hexdigest()[:16]
            assert 'opaque-run' not in json.dumps([r.id for r in recent])
            assert await ops.metrics_since() == NOW
            assert (await ops.catalog_state()).activated_at is None
            assert await metrics.purge(NOW + timedelta(days=91)) == 1

    asyncio.run(run())


def test_database_roles_keep_public_and_private_authorities_separate() -> None:
    async def run() -> None:
        async with private_database() as db:
            for role, query in [
                ('pequeverso_knowledge_runtime', 'SELECT * FROM assistant_private.sessions'),
                ('pequeverso_private_runtime', 'SELECT embedding FROM knowledge.chunks'),
                ('pequeverso_embedding_accounting', 'SELECT * FROM assistant_private.messages'),
                ('pequeverso_private_runtime', 'DELETE FROM assistant_private.spend_ledger'),
            ]:
                async with db.pool.connection() as conn:
                    # Role identifiers are fixed test fixtures; no user value is interpolated.
                    from psycopg import sql

                    await conn.execute(sql.SQL('SET LOCAL ROLE {}').format(sql.Identifier(role)))
                    with pytest.raises(psycopg.errors.InsufficientPrivilege):
                        await conn.execute(query)
                    await conn.rollback()

    asyncio.run(run())
