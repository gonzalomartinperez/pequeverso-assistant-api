"""Aggregate queries for the operations summary and the run-metrics store (no content)."""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime, timedelta

from app.adapters.sqlite.database import Database
from app.adapters.sqlite.stores import parse_ts, ts
from app.application.operations import CatalogState, DailyRow, RecentRun, RunWindow, Spend, Tokens
from app.application.ports import RunMetric, RunOutcome

OUTCOMES = tuple(o.value for o in RunOutcome)
METRICS_RETENTION = timedelta(days=90)
_SPEND = (
    "SELECT coalesce(sum(CASE WHEN status = 'settled' THEN actual_micro END), 0),"
    " coalesce(sum(CASE WHEN status = 'unreported' THEN reserved_micro END), 0),"
    " coalesce(sum(CASE WHEN status = 'pending' THEN reserved_micro END), 0)"
    ' FROM spend_ledger WHERE {} = ?'
)
_TOKENS = (
    'SELECT coalesce(sum(l.input_tokens), 0), coalesce(sum(l.cached_input_tokens), 0),'
    ' coalesce(sum(l.output_tokens), 0), coalesce(sum(l.reasoning_tokens), 0), count(*)'
    ' FROM spend_ledger l JOIN run_metrics m ON m.run_id = l.run_id'
    " WHERE l.status = 'settled' AND m.started_at >= ?"
)


def _dt(value: str | None) -> datetime | None:
    return parse_ts(value) if value else None


def _tokens(row: sqlite3.Row | tuple[int, ...]) -> Tokens:
    return Tokens(int(row[0]), int(row[1]), int(row[2]), int(row[3]), int(row[4]))


class SqliteRunMetrics:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def record(self, metric: RunMetric) -> None:
        await self._db.write(
            lambda c: c.execute(
                'INSERT OR IGNORE INTO run_metrics (run_id, started_at, ended_at, day, outcome, code,'
                ' model_call, replaced, language, first_delta_ms, total_ms)'
                ' VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                (
                    metric.run_id,
                    ts(metric.started_at),
                    ts(metric.ended_at),
                    metric.started_at.strftime('%Y-%m-%d'),
                    metric.outcome.value,
                    metric.code.value if metric.code else None,
                    int(metric.model_call),
                    int(metric.replaced),
                    metric.language.value if metric.language else None,
                    metric.first_delta_ms,
                    metric.total_ms,
                ),
            )
        )

    async def purge(self, now: datetime) -> int:
        cutoff = ts(now - METRICS_RETENTION)

        def work(c: sqlite3.Connection) -> int:
            return c.execute('DELETE FROM run_metrics WHERE started_at < ?', (cutoff,)).rowcount

        return await self._db.write(work)


class SqliteOperationsQueries:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def spend(self, column: str, value: str) -> Spend:
        if column not in ('month', 'day'):
            raise ValueError('spend period must be month or day')
        row = await self._db.read(lambda c: c.execute(_SPEND.format(column), (value,)).fetchone())
        return Spend(int(row[0]), int(row[1]), int(row[2]))

    async def tokens(self, since: datetime) -> Tokens:
        row = await self._db.read(lambda c: c.execute(_TOKENS, (ts(since),)).fetchone())
        return _tokens(row)

    async def run_window(self, since: datetime) -> RunWindow:
        def work(c: sqlite3.Connection) -> RunWindow:
            counts = dict.fromkeys(OUTCOMES, 0)
            for outcome, n in c.execute(
                'SELECT outcome, count(*) FROM run_metrics WHERE started_at >= ? GROUP BY outcome',
                (ts(since),),
            ):
                counts[outcome] = int(n)
            failures = {
                code: int(n)
                for code, n in c.execute(
                    'SELECT code, count(*) FROM run_metrics WHERE started_at >= ? AND code IS NOT NULL'
                    ' GROUP BY code ORDER BY code',
                    (ts(since),),
                )
            }
            replaced = int(
                c.execute(
                    'SELECT count(*) FROM run_metrics WHERE started_at >= ? AND replaced = 1', (ts(since),)
                ).fetchone()[0]
            )
            first = [
                int(r[0])
                for r in c.execute(
                    'SELECT first_delta_ms FROM run_metrics WHERE started_at >= ? AND model_call = 1'
                    ' AND first_delta_ms IS NOT NULL',
                    (ts(since),),
                )
            ]
            total = [
                int(r[0])
                for r in c.execute(
                    "SELECT total_ms FROM run_metrics WHERE started_at >= ? AND outcome = 'completed'"
                    ' AND model_call = 1',
                    (ts(since),),
                )
            ]
            return RunWindow(counts, failures, replaced, first, total)

        return await self._db.read(work)

    async def daily(self, since_day: str) -> list[DailyRow]:
        def work(c: sqlite3.Connection) -> list[DailyRow]:
            days: dict[str, dict[str, int]] = {}
            for day, outcome, n in c.execute(
                'SELECT day, outcome, count(*) FROM run_metrics WHERE day >= ? GROUP BY day, outcome',
                (since_day,),
            ):
                days.setdefault(day, dict.fromkeys(OUTCOMES, 0))[outcome] = int(n)
            spend: dict[str, Spend] = {}
            tokens: dict[str, Tokens] = {}
            for row in c.execute(
                "SELECT day, coalesce(sum(CASE WHEN status = 'settled' THEN actual_micro END), 0),"
                " coalesce(sum(CASE WHEN status = 'unreported' THEN reserved_micro END), 0),"
                " coalesce(sum(CASE WHEN status = 'pending' THEN reserved_micro END), 0),"
                ' coalesce(sum(input_tokens), 0), coalesce(sum(cached_input_tokens), 0),'
                ' coalesce(sum(output_tokens), 0), coalesce(sum(reasoning_tokens), 0),'
                " sum(CASE WHEN status = 'settled' THEN 1 ELSE 0 END)"
                ' FROM spend_ledger WHERE day >= ? GROUP BY day',
                (since_day,),
            ):
                spend[row[0]] = Spend(int(row[1]), int(row[2]), int(row[3]))
                tokens[row[0]] = Tokens(int(row[4]), int(row[5]), int(row[6]), int(row[7]), int(row[8]))
                days.setdefault(row[0], dict.fromkeys(OUTCOMES, 0))
            return [
                DailyRow(day, counts, spend.get(day, Spend()), tokens.get(day, Tokens()))
                for day, counts in sorted(days.items())
            ]

        return await self._db.read(work)

    async def metrics_since(self) -> datetime | None:
        row = await self._db.read(lambda c: c.execute('SELECT min(started_at) FROM run_metrics').fetchone())
        return _dt(row[0])

    async def recent(self, limit: int) -> list[RecentRun]:
        rows = await self._db.read(
            lambda c: c.execute(
                'SELECT run_id, started_at, outcome, code, model_call, replaced, language, first_delta_ms,'
                ' total_ms FROM run_metrics ORDER BY started_at DESC LIMIT ?',
                (limit,),
            ).fetchall()
        )
        return [
            RecentRun(
                id=hashlib.sha256(row['run_id'].encode()).hexdigest()[:16],
                started_at=parse_ts(row['started_at']),
                outcome=row['outcome'],
                code=row['code'],
                model_call=bool(row['model_call']),
                replaced=bool(row['replaced']),
                language=row['language'],
                first_delta_ms=row['first_delta_ms'],
                total_ms=row['total_ms'],
            )
            for row in rows
        ]

    async def catalog_state(self) -> CatalogState:
        row = await self._db.read(
            lambda c: c.execute(
                'SELECT s.activated_at, st.last_attempt_at, st.last_failure, st.last_failure_at'
                ' FROM catalog_state st LEFT JOIN catalog_snapshots s ON s.sha256 = st.active_sha256'
                ' WHERE st.id = 1'
            ).fetchone()
        )
        return CatalogState(_dt(row[0]), _dt(row[1]), row[2], _dt(row[3]))
