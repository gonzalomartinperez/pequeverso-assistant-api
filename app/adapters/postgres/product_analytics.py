"""Atomic, content-free analytics on the existing private pool. Runtime never migrates."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.adapters.postgres.database import PostgresDatabase
from app.application.product_analytics import Bucket, QuotaExceededError
from app.domain.product_analytics import Event, Selection

MIGRATION = Path(__file__).with_name('005_product_analytics.sql')


class PostgresProductAnalytics:
    def __init__(self, database: PostgresDatabase) -> None:
        self.database = database

    async def ready(self) -> bool:
        if not await self.database.runtime_ownership_alive():
            return False
        async with self.database.pool.connection() as connection:
            row = await (
                await connection.execute(
                    'SELECT checksum FROM assistant_private.analytics_schema WHERE version=1'
                )
            ).fetchone()
        return row is not None and row['checksum'] == hashlib.sha256(MIGRATION.read_bytes()).hexdigest()

    async def ingest(self, event: Event, now: datetime) -> bool:
        now = now.astimezone(UTC)
        day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        minute = now.replace(second=0, microsecond=0)
        async with self.database.pool.connection() as connection, connection.transaction():
            await connection.execute("SET LOCAL statement_timeout='2000ms'")
            await connection.execute("SET LOCAL lock_timeout='500ms'")
            await connection.execute('SELECT pg_advisory_xact_lock(684721028)')
            # Each operation prunes a bounded number; expiry predicates apply even during backlog.
            await connection.execute(
                'DELETE FROM assistant_private.analytics_dedupe WHERE digest IN (SELECT digest FROM assistant_private.analytics_dedupe WHERE received_at <= %s ORDER BY received_at LIMIT 999)',
                (now - timedelta(hours=24),),
            )
            await connection.execute(
                'DELETE FROM assistant_private.analytics_quotas WHERE (period,bucket) IN (SELECT period,bucket FROM assistant_private.analytics_quotas WHERE bucket < %s ORDER BY bucket LIMIT 1000)',
                (day - timedelta(days=1),),
            )
            await connection.execute(
                'DELETE FROM assistant_private.analytics_daily WHERE (day,route,section_id,viewport_bucket,event_name,cell_x,cell_y) IN (SELECT day,route,section_id,viewport_bucket,event_name,cell_x,cell_y FROM assistant_private.analytics_daily WHERE day < %s ORDER BY day LIMIT 1000)',
                (day - timedelta(days=92),),
            )
            existing = await (
                await connection.execute(
                    'SELECT received_at FROM assistant_private.analytics_dedupe WHERE digest=%s',
                    (event.digest,),
                )
            ).fetchone()
            if existing is not None and existing['received_at'] > now - timedelta(hours=24):
                return False
            if existing is not None:
                await connection.execute(
                    'DELETE FROM assistant_private.analytics_dedupe WHERE digest=%s', (event.digest,)
                )
            for period, bucket, maximum in (('minute', minute, 60), ('day', day, 10000)):
                current = await (
                    await connection.execute(
                        'SELECT accepted FROM assistant_private.analytics_quotas WHERE period=%s AND bucket=%s',
                        (period, bucket),
                    )
                ).fetchone()
                if current is not None and current['accepted'] >= maximum:
                    raise QuotaExceededError
                await connection.execute(
                    'INSERT INTO assistant_private.analytics_quotas(period,bucket,accepted) VALUES(%s,%s,1) ON CONFLICT(period,bucket) DO UPDATE SET accepted=analytics_quotas.accepted+1',
                    (period, bucket),
                )
            await connection.execute(
                'INSERT INTO assistant_private.analytics_dedupe(digest,received_at) VALUES(%s,%s)',
                (event.digest, now),
            )
            await connection.execute(
                'INSERT INTO assistant_private.analytics_daily(day,route,section_id,viewport_bucket,event_name,cell_x,cell_y,count,first_received,last_received) VALUES(%s,%s,%s,%s,%s,%s,%s,1,%s,%s) ON CONFLICT(day,route,section_id,viewport_bucket,event_name,cell_x,cell_y) DO UPDATE SET count=analytics_daily.count+1,first_received=LEAST(analytics_daily.first_received,EXCLUDED.first_received),last_received=GREATEST(analytics_daily.last_received,EXCLUDED.last_received)',
                (
                    day,
                    event.route,
                    event.section,
                    event.viewport,
                    event.name,
                    event.cell_x if event.cell_x is not None else -1,
                    event.cell_y if event.cell_y is not None else -1,
                    now,
                    now,
                ),
            )
        return True

    async def rows(self, start: datetime, end: datetime, selection: Selection) -> tuple[Bucket, ...]:
        async with self.database.pool.connection() as connection, connection.transaction():
            await connection.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            await connection.execute("SET LOCAL statement_timeout='2000ms'")
            cursor = await connection.execute(
                "SELECT day,event_name,cell_x,cell_y,sum(count)::bigint AS count,min(first_received) AS first,max(last_received) AS last FROM assistant_private.analytics_daily WHERE day >= %s AND day < %s AND (%s='all' OR route=%s) AND (%s='all' OR section_id=%s) AND (%s='all' OR viewport_bucket=%s) GROUP BY day,event_name,cell_x,cell_y ORDER BY day,event_name,cell_x,cell_y",
                (
                    start,
                    end,
                    selection.route,
                    selection.route,
                    selection.section_id,
                    selection.section_id,
                    selection.viewport_bucket,
                    selection.viewport_bucket,
                ),
            )
            rows = await cursor.fetchall()
        return tuple(
            Bucket(
                row['day'],
                row['event_name'],
                row['cell_x'],
                row['cell_y'],
                row['count'],
                row['first'],
                row['last'],
            )
            for row in rows
        )
