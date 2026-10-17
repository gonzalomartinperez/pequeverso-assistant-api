"""Content-free PostgreSQL operations queries; no session/history access is needed here."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta

from app.adapters.postgres.database import PostgresDatabase, Row
from app.application.operations import CatalogState, DailyRow, RecentRun, RunWindow, Spend, Tokens
from app.application.ports import RunMetric, RunOutcome

OUTCOMES = tuple(outcome.value for outcome in RunOutcome)


def _spend(row: Row) -> Spend:
    return Spend(int(row['confirmed']), int(row['estimated']), int(row['pending']))


def _tokens(row: Row) -> Tokens:
    return Tokens(
        int(row['input']),
        int(row['cached_input']),
        int(row['output']),
        int(row['reasoning']),
        int(row['runs_with_usage']),
    )


class PostgresRunMetrics:
    def __init__(self, db: PostgresDatabase) -> None:
        self._db = db

    async def record(self, metric: RunMetric) -> None:
        async with self._db.pool.connection() as conn:
            await conn.execute(
                'INSERT INTO assistant_private.run_metrics'
                '(run_id,started_at,ended_at,day,outcome,code,model_call,replaced,language,first_delta_ms,total_ms)'
                ' VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(run_id) DO NOTHING',
                (
                    metric.run_id,
                    metric.started_at,
                    metric.ended_at,
                    metric.started_at.strftime('%Y-%m-%d'),
                    metric.outcome.value,
                    metric.code.value if metric.code else None,
                    metric.model_call,
                    metric.replaced,
                    metric.language.value if metric.language else None,
                    metric.first_delta_ms,
                    metric.total_ms,
                ),
            )

    async def purge(self, now: datetime) -> int:
        async with self._db.pool.connection() as conn:
            return (
                await conn.execute(
                    'DELETE FROM assistant_private.run_metrics WHERE started_at<%s',
                    (now - timedelta(days=90),),
                )
            ).rowcount


class PostgresOperationsQueries:
    def __init__(self, private_db: PostgresDatabase, public_db: PostgresDatabase) -> None:
        self._db = private_db
        self._public = public_db

    async def spend(self, column: str, value: str) -> Spend:
        if column not in ('month', 'day'):
            raise ValueError('spend period must be month or day')
        async with self._db.pool.connection() as conn:
            row = await (
                await conn.execute(
                    "SELECT coalesce(sum(actual_micro) FILTER(WHERE status='settled'),0) AS confirmed,"
                    "coalesce(sum(reserved_micro) FILTER(WHERE status='unreported'),0) AS estimated,"
                    "coalesce(sum(reserved_micro) FILTER(WHERE status='pending'),0) AS pending"
                    " FROM assistant_private.spend_ledger WHERE (%s='month' AND month=%s) OR (%s='day' AND day=%s)",
                    (column, value, column, value),
                )
            ).fetchone()
        assert row is not None
        return _spend(row)

    async def tokens(self, since: datetime) -> Tokens:
        async with self._db.pool.connection() as conn:
            row = await (
                await conn.execute(
                    'SELECT coalesce(sum(l.input_tokens),0) AS input,coalesce(sum(l.cached_input_tokens),0) AS cached_input,'
                    'coalesce(sum(l.output_tokens),0) AS output,coalesce(sum(l.reasoning_tokens),0) AS reasoning,'
                    'count(*) AS runs_with_usage FROM assistant_private.spend_ledger l'
                    ' JOIN assistant_private.run_metrics m ON m.run_id=l.run_id'
                    " WHERE l.status='settled' AND m.started_at>=%s",
                    (since,),
                )
            ).fetchone()
        assert row is not None
        return _tokens(row)

    async def run_window(self, since: datetime) -> RunWindow:
        async with self._db.pool.connection() as conn:
            await conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            counts = dict.fromkeys(OUTCOMES, 0)
            for row in await (
                await conn.execute(
                    'SELECT outcome,count(*) AS n FROM assistant_private.run_metrics WHERE started_at>=%s GROUP BY outcome',
                    (since,),
                )
            ).fetchall():
                counts[row['outcome']] = int(row['n'])
            failure_rows = await (
                await conn.execute(
                    'SELECT code,count(*) AS n FROM assistant_private.run_metrics WHERE started_at>=%s AND code IS NOT NULL'
                    ' GROUP BY code ORDER BY code',
                    (since,),
                )
            ).fetchall()
            replaced = await (
                await conn.execute(
                    'SELECT count(*) AS n FROM assistant_private.run_metrics WHERE started_at>=%s AND replaced',
                    (since,),
                )
            ).fetchone()
            timings = await (
                await conn.execute(
                    'SELECT first_delta_ms,total_ms,outcome FROM assistant_private.run_metrics'
                    ' WHERE started_at>=%s AND model_call',
                    (since,),
                )
            ).fetchall()
        assert replaced is not None
        return RunWindow(
            counts,
            {r['code']: int(r['n']) for r in failure_rows},
            int(replaced['n']),
            [int(r['first_delta_ms']) for r in timings if r['first_delta_ms'] is not None],
            [int(r['total_ms']) for r in timings if r['outcome'] == 'completed'],
        )

    async def daily(self, since_day: str) -> list[DailyRow]:
        async with self._db.pool.connection() as conn:
            await conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            metric_rows = await (
                await conn.execute(
                    'SELECT day,outcome,count(*) AS n FROM assistant_private.run_metrics WHERE day>=%s GROUP BY day,outcome',
                    (since_day,),
                )
            ).fetchall()
            ledger_rows = await (
                await conn.execute(
                    "SELECT day,coalesce(sum(actual_micro) FILTER(WHERE status='settled'),0) AS confirmed,"
                    "coalesce(sum(reserved_micro) FILTER(WHERE status='unreported'),0) AS estimated,"
                    "coalesce(sum(reserved_micro) FILTER(WHERE status='pending'),0) AS pending,"
                    'coalesce(sum(input_tokens),0) AS input,coalesce(sum(cached_input_tokens),0) AS cached_input,'
                    'coalesce(sum(output_tokens),0) AS output,coalesce(sum(reasoning_tokens),0) AS reasoning,'
                    "count(*) FILTER(WHERE status='settled') AS runs_with_usage"
                    ' FROM assistant_private.spend_ledger WHERE day>=%s GROUP BY day',
                    (since_day,),
                )
            ).fetchall()
        days: dict[str, dict[str, int]] = {}
        for row in metric_rows:
            days.setdefault(row['day'], dict.fromkeys(OUTCOMES, 0))[row['outcome']] = int(row['n'])
        ledger = {r['day']: r for r in ledger_rows}
        for day in ledger:
            days.setdefault(day, dict.fromkeys(OUTCOMES, 0))
        return [
            DailyRow(
                day,
                counts,
                _spend(ledger[day]) if day in ledger else Spend(),
                _tokens(ledger[day]) if day in ledger else Tokens(),
            )
            for day, counts in sorted(days.items())
        ]

    async def metrics_since(self) -> datetime | None:
        async with self._db.pool.connection() as conn:
            row = await (
                await conn.execute('SELECT min(started_at) AS started FROM assistant_private.run_metrics')
            ).fetchone()
        return row['started'] if row else None

    async def recent(self, limit: int) -> list[RecentRun]:
        if type(limit) is not int or not 0 <= limit <= 100:
            raise ValueError('recent operations limit must be between zero and100')
        async with self._db.pool.connection() as conn:
            rows = await (
                await conn.execute(
                    'SELECT run_id,started_at,outcome,code,model_call,replaced,language,first_delta_ms,total_ms'
                    ' FROM assistant_private.run_metrics ORDER BY started_at DESC,run_id LIMIT %s',
                    (limit,),
                )
            ).fetchall()
        return [
            RecentRun(
                hashlib.sha256(row['run_id'].encode()).hexdigest()[:16],
                row['started_at'],
                row['outcome'],
                row['code'],
                row['model_call'],
                row['replaced'],
                row['language'],
                row['first_delta_ms'],
                row['total_ms'],
            )
            for row in rows
        ]

    async def catalog_state(self) -> CatalogState:
        async with self._public.pool.connection() as conn:
            row = await (
                await conn.execute(
                    'SELECT activated_at,last_attempt_at,last_failure,last_failure_at FROM knowledge.state WHERE id=1',
                )
            ).fetchone()
        assert row is not None
        return CatalogState(
            row['activated_at'], row['last_attempt_at'], row['last_failure'], row['last_failure_at']
        )
