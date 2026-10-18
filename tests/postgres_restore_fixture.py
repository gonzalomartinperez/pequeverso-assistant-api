"""Synthetic fixture seed for the isolated image restore smoke; never public knowledge."""

import asyncio
import hashlib
from datetime import UTC, datetime, timedelta

from psycopg.conninfo import conninfo_to_dict

from app.adapters.postgres.database import PostgresDatabase
from app.adapters.postgres.private_ledger import PostgresLedger
from app.adapters.postgres.private_stores import PostgresMessageStore, PostgresSessionStore
from app.domain.budget import Usage
from app.domain.conversation import Message, Role, Session
from tests.test_postgres_knowledge import DSN


async def seed() -> None:
    if DSN is None:
        raise ValueError('isolated fixture DSN required')
    values = conninfo_to_dict(DSN)
    if (
        values.get('host') != '127.0.0.1'
        or values.get('port') != '55439'
        or values.get('dbname') != 'pv_knowledge_test'
    ):
        raise ValueError('restore fixture is restricted to the isolated disposable database')
    db = PostgresDatabase(DSN)
    await db.open()
    try:
        now = datetime.now(UTC)
        await PostgresSessionStore(db).create(
            Session('restore-synthetic-session', 'restore-synthetic-csrf', now, now, now + timedelta(days=1)),
            hashlib.sha256(b'restore-synthetic-secret').digest(),
        )
        await PostgresMessageStore(db).append(
            'restore-synthetic-session',
            Message('restore-synthetic-message', Role.USER, 'Synthetic restore probe.', now),
        )
        ledger = PostgresLedger(db)
        for id_, amount in [
            ('restore-settled', 10),
            ('restore-unknown', 20),
            ('embedding:index:restore', 30),
        ]:
            assert await ledger.reserve(
                id_, amount, now.strftime('%Y-%m'), now.strftime('%Y-%m-%d'), lambda **_: True
            )
        await ledger.settle('restore-settled', 1, Usage(9, 2, reasoning_tokens=1), 'fixture')
        await ledger.mark_unreported('restore-unknown')
    finally:
        await db.close()


if __name__ == '__main__':
    asyncio.run(seed())
