"""SQLite access on one dedicated thread.

All statements run on a single worker thread with one connection, so the event loop never
blocks and writes are serialized in-process. Write transactions use `BEGIN IMMEDIATE`, which
also serializes writers across processes sharing the file. WAL keeps readers unblocked.
"""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import TypeVar

T = TypeVar('T')

MIGRATIONS = Path(__file__).resolve().parents[3] / 'migrations'


class Database:
    def __init__(self, path: str) -> None:
        self._path = path
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='sqlite')
        self._connection: sqlite3.Connection | None = None

    async def open(self) -> None:
        await self._submit(self._open)

    def _open(self) -> None:
        if self._path != ':memory:':
            Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self._path, isolation_level=None, check_same_thread=False, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA foreign_keys = ON')
        connection.execute('PRAGMA busy_timeout = 5000')
        if self._path != ':memory:':
            connection.execute('PRAGMA journal_mode = WAL')
            connection.execute('PRAGMA synchronous = NORMAL')
        self._connection = connection
        _migrate(connection)

    async def close(self) -> None:
        if self._connection is not None:
            await self._submit(self._connection.close)
            self._connection = None
        self._executor.shutdown(wait=True)

    async def read(self, work: Callable[[sqlite3.Connection], T]) -> T:
        return await self._submit(lambda: work(self._require()))

    async def write(self, work: Callable[[sqlite3.Connection], T]) -> T:
        """Run `work` inside one IMMEDIATE transaction, committed on success."""

        def transaction() -> T:
            connection = self._require()
            connection.execute('BEGIN IMMEDIATE')
            try:
                result = work(connection)
            except BaseException:
                connection.execute('ROLLBACK')
                raise
            connection.execute('COMMIT')
            return result

        return await self._submit(transaction)

    async def ping(self) -> bool:
        return await self.read(lambda c: c.execute('SELECT 1').fetchone()[0] == 1)

    def _require(self) -> sqlite3.Connection:
        if self._connection is None:
            raise RuntimeError('database is not open')
        return self._connection

    async def _submit(self, work: Callable[[], T]) -> T:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, work)


def _migrate(connection: sqlite3.Connection) -> None:
    current = connection.execute('PRAGMA user_version').fetchone()[0]
    for script in sorted(MIGRATIONS.glob('[0-9][0-9][0-9]_*.sql')):
        version = int(script.name[:3])
        if version <= current:
            continue
        connection.execute('BEGIN IMMEDIATE')
        try:
            for statement in _statements(script.read_text()):
                connection.execute(statement)
            connection.execute(f'PRAGMA user_version = {version}')
        except BaseException:
            connection.execute('ROLLBACK')
            raise
        connection.execute('COMMIT')


def _statements(sql: str) -> list[str]:
    lines = [line for line in sql.splitlines() if not line.strip().startswith('--')]
    return [statement.strip() for statement in '\n'.join(lines).split(';') if statement.strip()]
