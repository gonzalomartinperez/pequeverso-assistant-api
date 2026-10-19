"""Requires an explicitly isolated real PG, with separate migrator/runtime logins.

No DSN means SKIP, never fake persistence acceptance. No external fixture is started here.
"""

import asyncio
import hashlib
import os
import secrets
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from datetime import timedelta
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from app.adapters.postgres.database import PostgresDatabase
from app.adapters.postgres.product_analytics import (
    CLASSIFICATION_MIGRATION,
    MIGRATION,
    PostgresProductAnalytics,
)
from app.application.product_analytics import AnalyticsService, QuotaExceededError
from app.domain.product_analytics import Selection
from app.presentation.product_analytics import EventIn, ReportOut
from tests.test_product_analytics import NOW, event

ADMIN = os.environ.get('TEST_PRODUCT_ANALYTICS_ADMIN_DSN') or os.environ.get('TEST_KNOWLEDGE_DSN')
RUNTIME = os.environ.get('TEST_PRODUCT_ANALYTICS_DSN')
pytestmark = pytest.mark.skipif(
    not ADMIN,
    reason='requires exact isolated PG fixture; provisions own nonowner runtime if not supplied',
)


def isolated_target(dsn: str) -> dict[str, str]:
    try:
        info = conninfo_to_dict(dsn)
    except psycopg.ProgrammingError:
        raise ValueError('invalid isolated fixture DSN') from None
    if (
        info.get('host') != '127.0.0.1'
        or info.get('port') != '55439'
        or info.get('dbname') != 'pv_knowledge_test'
        or info.get('hostaddr') not in (None, '127.0.0.1')
        or any(info.get(name) for name in ('service', 'options', 'replication'))
    ):
        raise ValueError('analytics tests require the exact isolated localhost fixture database')
    return info


@asynccontextmanager
async def stores() -> AsyncIterator[tuple[PostgresDatabase, PostgresDatabase, PostgresProductAnalytics]]:
    assert ADMIN
    info = isolated_target(ADMIN)
    if RUNTIME:
        isolated_target(RUNTIME)
        assert ADMIN != RUNTIME
    admin = PostgresDatabase(ADMIN)
    async with AsyncExitStack() as resources:
        resources.push_async_callback(admin.close)
        await admin.open()
        await admin.migrate()
        role = 'pv_analytics_' + uuid4().hex
        created = False

        async def drop_role() -> None:
            if created:
                for _ in range(20):
                    async with admin.pool.connection() as connection:
                        active = await (
                            await connection.execute(
                                'SELECT count(*) AS count FROM pg_stat_activity WHERE usename=%s', (role,)
                            )
                        ).fetchone()
                    if active is not None and active['count'] == 0:
                        async with admin.pool.connection() as connection:
                            await connection.execute(
                                sql.SQL('DROP ROLE IF EXISTS {}').format(sql.Identifier(role))
                            )
                        return
                    await asyncio.sleep(0.05)
                raise RuntimeError('isolated analytics fixture still has clients; role retained')

        resources.push_async_callback(drop_role)
        if RUNTIME:
            runtime_dsn = RUNTIME
        else:
            password = secrets.token_hex(24)  # Synthetic, unique to this isolated fixture only.
            async with admin.pool.connection() as connection:
                await connection.execute(
                    sql.SQL(
                        'CREATE ROLE {} LOGIN INHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD {}'
                    ).format(sql.Identifier(role), sql.Literal(password))
                )
                created = True
                await connection.execute(
                    sql.SQL('GRANT pequeverso_private_runtime TO {} WITH INHERIT TRUE, SET FALSE').format(
                        sql.Identifier(role)
                    )
                )
            runtime_dsn = make_conninfo(**{**info, 'user': role, 'password': password})
        runtime = PostgresDatabase(runtime_dsn)
        resources.push_async_callback(runtime.close)
        await runtime.open()
        async with runtime.pool.connection() as connection:
            row = await (
                await connection.execute(
                    "SELECT rolsuper,rolcreaterole,rolcreatedb,current_user AS identity,pg_has_role(current_user,'pequeverso_private_runtime','MEMBER') AS member FROM pg_roles WHERE rolname=current_user"
                )
            ).fetchone()
            owner = await (
                await connection.execute(
                    "SELECT pg_get_userbyid(relowner) AS owner FROM pg_class WHERE oid='assistant_private.analytics_daily'::regclass"
                )
            ).fetchone()
            assert (
                row and owner and not row['rolsuper'] and not row['rolcreaterole'] and not row['rolcreatedb']
            )
            assert row['member'] and row['identity'] != owner['owner']
        async with admin.pool.connection() as connection:
            await connection.execute(
                'TRUNCATE assistant_private.analytics_dedupe,assistant_private.analytics_quotas,assistant_private.analytics_daily,assistant_private.analytics_daily_v2'
            )
        async with runtime.runtime_ownership():
            yield admin, runtime, PostgresProductAnalytics(runtime)


def test_real_atomic_duplicate_quota_and_report_reconciliation() -> None:
    async def run() -> None:
        async with stores() as (_, runtime, repo):
            assert await repo.ready()
            values = [EventIn.model_validate(event()).event() for _ in range(61)]
            semaphore = asyncio.Semaphore(8)

            async def ingest(value: object) -> bool:
                async with semaphore:
                    return await repo.ingest(value, NOW)  # type: ignore[arg-type]

            results = await asyncio.gather(*(ingest(value) for value in values), return_exceptions=True)
            assert sum(value is True for value in results) == 60
            assert sum(isinstance(value, QuotaExceededError) for value in results) == 1
            accepted = next(value for value, result in zip(values, results, strict=True) if result is True)
            assert await repo.ingest(accepted, NOW) is False
            report = ReportOut.model_validate(
                await AnalyticsService(repo, synthetic=True).report(
                    NOW, Selection(route='/', section_id='hero')
                )
            )
            assert report.totals.public_clicks == 60 and report.grid.visible_clicks == 60
            async with runtime.pool.connection() as connection:
                row = await (
                    await connection.execute(
                        'SELECT count(*) AS count FROM assistant_private.analytics_dedupe'
                    )
                ).fetchone()
            assert row and row['count'] == 60
            assert await repo.ingest(EventIn.model_validate(event()).event(), NOW + timedelta(minutes=1))

    asyncio.run(run())


def test_real_checksum_and_grants_fail_closed() -> None:
    async def run() -> None:
        async with stores() as (admin, runtime, repo):
            async with runtime.pool.connection() as connection:
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    async with connection.transaction():
                        await connection.execute(
                            "UPDATE assistant_private.analytics_schema SET checksum=repeat('a',64)"
                        )
            async with admin.pool.connection() as connection:
                row = await (
                    await connection.execute(
                        "SELECT has_table_privilege('pequeverso_knowledge_runtime','assistant_private.analytics_daily','SELECT') AS knowledge,has_table_privilege('pequeverso_embedding_accounting','assistant_private.analytics_daily','SELECT') AS accounting"
                    )
                ).fetchone()
                assert row and not row['knowledge'] and not row['accounting']
                await connection.execute(
                    "UPDATE assistant_private.analytics_schema SET checksum=repeat('a',64)"
                )
            assert not await repo.ready()
            with pytest.raises(RuntimeError, match='checksum mismatch'):
                await admin.migrate()
            async with admin.pool.connection() as connection:
                await connection.execute(
                    'UPDATE assistant_private.analytics_schema SET checksum=%s',
                    (hashlib.sha256(MIGRATION.read_bytes()).hexdigest(),),
                )
            assert await repo.ready()

    asyncio.run(run())


def test_real_filters_expiry_and_day_quota_rollback() -> None:
    async def run() -> None:
        async with stores() as (admin, _, repo):
            first = EventIn.model_validate(event()).event()
            assert await repo.ingest(first, NOW)
            assert await repo.ingest(
                EventIn.model_validate(event(route='/grafismo-fonetico/', section_id='incluye')).event(), NOW
            )
            service = AnalyticsService(repo, synthetic=True)
            filtered = ReportOut.model_validate(
                await service.report(NOW, Selection(route='/grafismo-fonetico/', section_id='incluye'))
            )
            assert filtered.totals.public_clicks == 1 and filtered.countries[0].count == 1
            async with admin.pool.connection() as connection:
                await connection.execute(
                    "UPDATE assistant_private.analytics_quotas SET accepted=10000 WHERE period='day'"
                )
            with pytest.raises(QuotaExceededError):
                await repo.ingest(EventIn.model_validate(event()).event(), NOW + timedelta(minutes=1))
            async with admin.pool.connection() as connection:
                row = await (
                    await connection.execute(
                        'SELECT count(*) AS count FROM assistant_private.analytics_dedupe'
                    )
                ).fetchone()
                assert row and row['count'] == 2
            # A replay outside the explicitly bounded 24h dedupe horizon is a new received event.
            assert await repo.ingest(first, NOW + timedelta(hours=24))

    asyncio.run(run())


def test_real_classification_isolation_preserves_global_dedupe_and_concurrent_quota() -> None:
    async def run() -> None:
        async with stores() as (_, runtime, fixture):
            production = PostgresProductAnalytics(runtime, synthetic=False)
            first = EventIn.model_validate(event()).event()
            assert await fixture.ingest(first, NOW)
            assert await production.ingest(first, NOW) is False
            values = [EventIn.model_validate(event()).event(country='AR') for _ in range(60)]
            semaphore = asyncio.Semaphore(8)

            async def ingest(index: int) -> bool:
                async with semaphore:
                    repository = production if index % 2 else fixture
                    return await repository.ingest(values[index], NOW)

            results = await asyncio.gather(*(ingest(i) for i in range(60)), return_exceptions=True)
            assert sum(result is True for result in results) == 59
            assert sum(isinstance(result, QuotaExceededError) for result in results) == 1
            reports = [
                ReportOut.model_validate(
                    await AnalyticsService(repository, synthetic=synthetic).report(NOW, Selection())
                )
                for repository, synthetic in ((fixture, True), (production, False))
            ]
            assert reports[0].synthetic is True and reports[1].synthetic is False
            assert sum(report.totals.public_clicks for report in reports) == 60
            assert reports[1].totals.public_clicks in (29, 30)
            assert [(row.code, row.count) for row in reports[1].countries] == [
                ('AR', reports[1].totals.public_clicks)
            ]

    asyncio.run(run())


def test_real_v2_marker_grants_and_one_time_backfill_do_not_relabel_or_resurrect() -> None:
    async def run() -> None:
        async with stores() as (admin, runtime, repo):
            checksum = hashlib.sha256(CLASSIFICATION_MIGRATION.read_bytes()).hexdigest()
            async with runtime.pool.connection() as connection:
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    async with connection.transaction():
                        await connection.execute(
                            "UPDATE assistant_private.analytics_schema_v2 SET checksum=repeat('a',64)"
                        )
            async with admin.pool.connection() as connection:
                permissions = await (
                    await connection.execute(
                        "SELECT has_table_privilege('pequeverso_knowledge_runtime','assistant_private.analytics_daily_v2','SELECT') AS knowledge,has_table_privilege('pequeverso_embedding_accounting','assistant_private.analytics_daily_v2','SELECT') AS accounting"
                    )
                ).fetchone()
                assert permissions and not permissions['knowledge'] and not permissions['accounting']
                await connection.execute(
                    "INSERT INTO assistant_private.analytics_daily(day,route,section_id,viewport_bucket,event_name,cell_x,cell_y,count,first_received,last_received) VALUES(%s,'/','hero','desktop','public_click',0,0,3,%s,%s)",
                    (NOW.replace(hour=0, minute=0, second=0, microsecond=0), NOW, NOW),
                )
                # Emulate the real pre006 state only inside this explicitly isolated fixture.
                await connection.execute('DELETE FROM assistant_private.analytics_schema_v2')
                await connection.execute('DROP TABLE assistant_private.analytics_schema_v2')
            await admin.migrate()
            synthetic = ReportOut.model_validate(
                await AnalyticsService(repo, synthetic=True).report(NOW, Selection())
            )
            production = PostgresProductAnalytics(runtime, synthetic=False)
            assert synthetic.totals.public_clicks == 3
            assert [(row.code, row.count) for row in synthetic.countries] == [('unknown', 3)]
            assert not await production.rows(NOW - timedelta(days=1), NOW + timedelta(days=1), Selection())
            async with admin.pool.connection() as connection:
                await connection.execute('DELETE FROM assistant_private.analytics_daily_v2')
            await admin.migrate()
            assert not await repo.rows(NOW - timedelta(days=1), NOW + timedelta(days=1), Selection())
            async with admin.pool.connection() as connection:
                await connection.execute(
                    "UPDATE assistant_private.analytics_schema_v2 SET checksum=repeat('a',64)"
                )
            try:
                assert not await repo.ready()
                with pytest.raises(RuntimeError, match='checksum mismatch'):
                    await admin.migrate()
            finally:
                async with admin.pool.connection() as connection:
                    await connection.execute(
                        'UPDATE assistant_private.analytics_schema_v2 SET checksum=%s', (checksum,)
                    )
            assert await repo.ready()

    asyncio.run(run())
