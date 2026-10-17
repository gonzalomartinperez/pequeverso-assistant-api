"""Explicitly owned bounded pool and migration entry point for public knowledge."""

from __future__ import annotations

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

    async def open(self) -> None:
        await self.pool.open(wait=True, timeout=5.0)

    async def close(self) -> None:
        await self.pool.close(timeout=5.0)

    async def migrate(self) -> None:
        """Only the explicit migration identity calls this; normal runtime never executes DDL."""
        async with self.pool.connection() as connection:
            await connection.execute('SELECT pg_advisory_xact_lock(684721023)')
            for name in ('001_knowledge.sql', '002_roles.sql'):
                await connection.execute(Path(__file__).with_name(name).read_text())
