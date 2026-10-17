"""Durable native PG budgeting shared by generation/query/index connections."""

from __future__ import annotations

from datetime import datetime, timedelta

from psycopg import AsyncConnection

from app.adapters.postgres.database import PostgresDatabase, Row
from app.application.ports import BudgetCheck
from app.domain.budget import Usage


async def _spent(conn: AsyncConnection[Row], month: str, day: str) -> tuple[int, int]:
    row = await (
        await conn.execute(
            'SELECT coalesce(sum(coalesce(actual_micro,reserved_micro)) FILTER(WHERE month=%s),0) AS month,'
            ' coalesce(sum(coalesce(actual_micro,reserved_micro)) FILTER(WHERE day=%s),0) AS day'
            ' FROM assistant_private.spend_ledger WHERE month=%s OR day=%s',
            (month, day, month, day),
        )
    ).fetchone()
    assert row is not None
    return int(row['month']), int(row['day'])


class PostgresLedger:
    def __init__(self, db: PostgresDatabase) -> None:
        self._db = db

    async def reserve(
        self, run_id: str, reservation_micro: int, month: str, day: str, allows: BudgetCheck
    ) -> bool:
        if type(reservation_micro) is not int or reservation_micro < 0:
            raise ValueError('reservation must be nonnegative integer microUSD')
        async with self._db.pool.connection() as conn:
            # Every process/purpose uses this database lock, not an in-process mutex.
            await conn.execute('SELECT pg_advisory_xact_lock(684721025)')
            month_spent, day_spent = await _spent(conn, month, day)
            if not allows(month_spent=month_spent, day_spent=day_spent, reservation=reservation_micro):
                return False
            await conn.execute(
                'INSERT INTO assistant_private.spend_ledger(run_id,month,day,reserved_micro) VALUES(%s,%s,%s,%s)',
                (run_id, month, day, reservation_micro),
            )
        return True

    async def settle(self, run_id: str, actual_micro: int, usage: Usage, model: str) -> None:
        async with self._db.pool.connection() as conn:
            updated = await conn.execute(
                'UPDATE assistant_private.spend_ledger SET actual_micro=%s,model=%s,input_tokens=%s,'
                'output_tokens=%s,cached_input_tokens=%s,cache_write_tokens=%s,reasoning_tokens=%s,'
                "status='settled',settled_at=CURRENT_TIMESTAMP WHERE run_id=%s AND actual_micro IS NULL",
                (
                    actual_micro,
                    model,
                    usage.input_tokens,
                    usage.output_tokens,
                    usage.cached_input_tokens,
                    usage.cache_write_tokens,
                    usage.reasoning_tokens,
                    run_id,
                ),
            )
            if updated.rowcount != 1:
                raise LookupError('no open reservation for this run')

    async def mark_unreported(self, run_id: str) -> None:
        async with self._db.pool.connection() as conn:
            await conn.execute(
                "UPDATE assistant_private.spend_ledger SET status='unreported' WHERE run_id=%s AND status='pending'",
                (run_id,),
            )

    async def abandon_pending(self) -> int:
        async with self._db.pool.connection() as conn:
            return (
                await conn.execute(
                    "UPDATE assistant_private.spend_ledger SET status=CASE WHEN actual_micro IS NOT NULL THEN 'settled'"
                    " ELSE 'unreported' END WHERE status='pending' AND run_id NOT LIKE 'embedding:index:%'",
                )
            ).rowcount

    async def abandon_index_pending(self) -> int:
        """Explicit index job calls only while holding the public exclusive indexing lock."""
        async with self._db.pool.connection() as conn:
            return (
                await conn.execute(
                    "UPDATE assistant_private.spend_ledger SET status=CASE WHEN actual_micro IS NOT NULL THEN 'settled'"
                    " ELSE 'unreported' END WHERE status='pending' AND run_id LIKE 'embedding:index:%'",
                )
            ).rowcount

    async def spent(self, month: str, day: str) -> tuple[int, int]:
        async with self._db.pool.connection() as conn:
            return await _spent(conn, month, day)


class PostgresRateLimiter:
    def __init__(self, db: PostgresDatabase) -> None:
        self._db = db

    async def hit(self, key: str, window_seconds: int, limit: int, now: datetime) -> bool:
        if window_seconds <= 0 or limit <= 0:
            raise ValueError('rate window and limit must be positive')
        window = int(now.timestamp()) // window_seconds * window_seconds
        async with self._db.pool.connection() as conn:
            row = await (
                await conn.execute(
                    'INSERT INTO assistant_private.rate_counters(key,window_start,count) VALUES(%s,%s,1)'
                    ' ON CONFLICT(key,window_start) DO UPDATE SET count=assistant_private.rate_counters.count+1'
                    ' WHERE assistant_private.rate_counters.count<%s RETURNING count',
                    (key, window, limit),
                )
            ).fetchone()
        return row is not None

    async def purge(self, now: datetime, keep: timedelta) -> int:
        async with self._db.pool.connection() as conn:
            return (
                await conn.execute(
                    'DELETE FROM assistant_private.rate_counters WHERE window_start<%s',
                    (int((now - keep).timestamp()),),
                )
            ).rowcount
