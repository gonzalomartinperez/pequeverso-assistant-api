"""Budget ledger and rate counters. Both check-and-insert inside one IMMEDIATE transaction."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta

from app.adapters.sqlite.database import Database
from app.application.ports import BudgetCheck
from app.domain.budget import Usage

_SPENT = 'SELECT coalesce(sum(coalesce(actual_micro, reserved_micro)), 0) FROM spend_ledger WHERE {} = ?'


def _spent(c: sqlite3.Connection, month: str, day: str) -> tuple[int, int]:
    month_spent = int(c.execute(_SPENT.format('month'), (month,)).fetchone()[0])
    day_spent = int(c.execute(_SPENT.format('day'), (day,)).fetchone()[0])
    return month_spent, day_spent


class SqliteLedger:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def reserve(
        self, run_id: str, reservation_micro: int, month: str, day: str, allows: BudgetCheck
    ) -> bool:
        def work(c: sqlite3.Connection) -> bool:
            month_spent, day_spent = _spent(c, month, day)
            if not allows(month_spent=month_spent, day_spent=day_spent, reservation=reservation_micro):
                return False
            c.execute(
                'INSERT INTO spend_ledger (run_id, month, day, reserved_micro, created_at)'
                " VALUES (?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))",
                (run_id, month, day, reservation_micro),
            )
            return True

        return await self._db.write(work)

    async def settle(self, run_id: str, actual_micro: int, usage: Usage, model: str) -> None:
        def work(c: sqlite3.Connection) -> None:
            updated = c.execute(
                'UPDATE spend_ledger SET actual_micro = ?, model = ?, input_tokens = ?, output_tokens = ?,'
                ' cached_input_tokens = ? WHERE run_id = ? AND actual_micro IS NULL',
                (
                    actual_micro,
                    model,
                    usage.input_tokens,
                    usage.output_tokens,
                    usage.cached_input_tokens,
                    run_id,
                ),
            ).rowcount
            if updated != 1:
                raise LookupError('no open reservation for this run')

        await self._db.write(work)

    async def spent(self, month: str, day: str) -> tuple[int, int]:
        return await self._db.read(lambda c: _spent(c, month, day))


class SqliteRateLimiter:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def hit(self, key: str, window_seconds: int, limit: int, now: datetime) -> bool:
        window = int(now.timestamp()) // window_seconds * window_seconds

        def work(c: sqlite3.Connection) -> bool:
            row = c.execute(
                'SELECT count FROM rate_counters WHERE key = ? AND window_start = ?', (key, window)
            ).fetchone()
            if row is not None and row[0] >= limit:
                return False
            c.execute(
                'INSERT INTO rate_counters (key, window_start, count) VALUES (?, ?, 1)'
                ' ON CONFLICT (key, window_start) DO UPDATE SET count = count + 1',
                (key, window),
            )
            return True

        return await self._db.write(work)

    async def purge(self, now: datetime, keep: timedelta) -> int:
        cutoff = int((now - keep).timestamp())

        def work(c: sqlite3.Connection) -> int:
            return c.execute('DELETE FROM rate_counters WHERE window_start < ?', (cutoff,)).rowcount

        return await self._db.write(work)
