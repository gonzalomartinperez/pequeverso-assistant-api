"""Budget reservations stay under the cutoff under concurrency, in-process and across processes."""

from __future__ import annotations

import asyncio
import multiprocessing
import sqlite3
from contextlib import closing
from decimal import Decimal
from pathlib import Path

from app.adapters.sqlite.database import Database
from app.adapters.sqlite.ledger import SqliteLedger
from app.domain.budget import BudgetPolicy, Usage, to_micro

POLICY = BudgetPolicy(to_micro(Decimal(10)), Decimal('0.10'), to_micro(Decimal(1)))  # daily cutoff 1.00 USD
RESERVATION = 3_000  # 0.003 USD → at most 333 reservations fit in one day


def _reserve_many(path: str, prefix: str, count: int) -> int:
    async def run() -> int:
        db = Database(path)
        await db.open()
        ledger = SqliteLedger(db)
        results = await asyncio.gather(
            *(
                ledger.reserve(f'{prefix}-{i}', RESERVATION, '2026-09', '2026-09-28', POLICY.allows)
                for i in range(count)
            )
        )
        await db.close()
        return sum(results)

    return asyncio.run(run())


def _total(path: str) -> int:
    with closing(sqlite3.connect(path)) as c:
        return int(c.execute('SELECT sum(reserved_micro) FROM spend_ledger').fetchone()[0])


def test_concurrent_reservations_never_exceed_the_cutoff(tmp_path: Path) -> None:
    path = str(tmp_path / 'ledger.sqlite3')
    accepted = _reserve_many(path, 'a', 500)
    assert accepted == POLICY.daily_cutoff_micro // RESERVATION == 333
    assert _total(path) <= POLICY.daily_cutoff_micro


def test_reservations_are_atomic_across_processes(tmp_path: Path) -> None:
    path = str(tmp_path / 'ledger.sqlite3')
    _reserve_many(path, 'init', 0)  # migrate once
    context = multiprocessing.get_context('spawn')
    with context.Pool(4) as pool:
        accepted = sum(pool.starmap(_reserve_many, [(path, f'p{i}', 150) for i in range(4)]))
    assert accepted == 333
    assert _total(path) <= POLICY.daily_cutoff_micro


def test_settlement_replaces_reservation_and_missing_usage_keeps_it(tmp_path: Path) -> None:
    async def run() -> None:
        db = Database(str(tmp_path / 'l.sqlite3'))
        await db.open()
        ledger = SqliteLedger(db)
        assert await ledger.reserve('r1', 5_000, '2026-09', '2026-09-28', POLICY.allows)
        assert await ledger.reserve('r2', 5_000, '2026-09', '2026-09-28', POLICY.allows)
        await ledger.settle('r1', 1_200, Usage(8000, 300, cached_input_tokens=6000), 'gpt-6-luna')
        assert await ledger.spent('2026-09', '2026-09-28') == (6_200, 6_200)
        try:
            await ledger.settle('r1', 10, Usage(1, 1), 'gpt-6-luna')
        except LookupError:
            pass
        else:
            raise AssertionError('double settlement must fail')
        await db.close()

    asyncio.run(run())
