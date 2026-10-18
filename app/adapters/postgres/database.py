"""Explicitly owned bounded pool and migration entry point for public knowledge."""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

Row = dict[str, Any]


class PostgresDatabase:
    def __init__(self, dsn: str, *, pool_size: int = 4, timeout_seconds: float = 3.0) -> None:
        if not 2 <= pool_size <= 8 or not 0.1 <= timeout_seconds <= 10:
            raise ValueError('public knowledge pool bounds are invalid')
        self.pool: AsyncConnectionPool[AsyncConnection[Row]] = AsyncConnectionPool(
            dsn,
            connection_class=AsyncConnection[Row],
            min_size=1,
            max_size=pool_size,
            max_waiting=16,
            timeout=timeout_seconds,
            open=False,
            kwargs={
                'row_factory': dict_row,
                'connect_timeout': 3,
                'options': '-c statement_timeout=3000 -c lock_timeout=3000 -c idle_in_transaction_session_timeout=10000',
            },
        )
        self._runtime_owner: AsyncConnection[Row] | None = None

    async def open(self) -> None:
        await self.pool.open(wait=True, timeout=5.0)

    async def close(self) -> None:
        await self.pool.close(timeout=5.0)

    async def ping(self) -> bool:
        async with self.pool.connection() as connection:
            row = await (await connection.execute('SELECT 1 AS ready')).fetchone()
        return row is not None and row['ready'] == 1

    @asynccontextmanager
    async def runtime_ownership(self) -> AsyncIterator[None]:
        """One stop-first private runtime. No takeover/recovery of another live instance.

        The explicit SQLite import shares this key and therefore cannot race the runtime.
        A lost connection makes admission unhealthy; this context never reacquires a lease.
        """
        if self._runtime_owner is not None:
            raise RuntimeError('PostgreSQL private runtime ownership is already active')
        async with self.pool.connection() as connection:
            try:
                await connection.set_autocommit(True)
                row = await (
                    await connection.execute('SELECT pg_try_advisory_lock(684721026) AS owned')
                ).fetchone()
                if row is None or not row['owned']:
                    raise RuntimeError('PostgreSQL private runtime is already owned')
                self._runtime_owner = connection
                yield
            finally:
                if self._runtime_owner is connection:
                    self._runtime_owner = None
                # Session lock is released even after cancellation, without a pooled stale lock.
                await connection.close()

    async def runtime_ownership_alive(self) -> bool:
        connection = self._runtime_owner
        if connection is None or connection.closed:
            return False
        try:
            row = await (
                await connection.execute(
                    "SELECT EXISTS(SELECT FROM pg_locks WHERE locktype='advisory'"
                    ' AND pid=pg_backend_pid() AND classid=0 AND objid=684721026'
                    " AND objsubid=1 AND mode='ExclusiveLock' AND granted) AS owned"
                )
            ).fetchone()
            return row is not None and row['owned'] is True
        except Exception:  # noqa: BLE001 - never reconnect/reacquire silently during admission
            return False

    async def migrate(self) -> None:
        """Only the explicit migration identity calls this; normal runtime never executes DDL."""
        async with self.pool.connection() as connection:
            await connection.execute('SELECT pg_advisory_xact_lock(684721023)')
            for name in (
                '001_knowledge.sql',
                '002_roles.sql',
                '003_private.sql',
                '004_accounting_policy.sql',
            ):
                await connection.execute(Path(__file__).with_name(name).read_text())
            analytics = Path(__file__).with_name('005_product_analytics.sql').read_bytes()
            checksum = hashlib.sha256(analytics).hexdigest()
            exists = await (
                await connection.execute(
                    "SELECT to_regclass('assistant_private.analytics_schema') AS relation"
                )
            ).fetchone()
            if exists is not None and exists['relation'] is not None:
                previous = await (
                    await connection.execute(
                        'SELECT checksum FROM assistant_private.analytics_schema WHERE version=1'
                    )
                ).fetchone()
                if previous is None or previous['checksum'] != checksum:
                    raise RuntimeError('product analytics migration checksum mismatch')
            await connection.execute(analytics.decode())
            await connection.execute(
                'INSERT INTO assistant_private.analytics_schema(version,checksum) VALUES(1,%s) ON CONFLICT(version) DO NOTHING',
                (checksum,),
            )
