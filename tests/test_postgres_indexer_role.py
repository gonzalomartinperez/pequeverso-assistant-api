"""Real least-privilege indexing; a table owner cannot substitute this capability proof."""

import asyncio

import pytest

from app.adapters.postgres.database import PostgresDatabase
from app.adapters.postgres.knowledge import PostgresKnowledgeStore
from tests.test_postgres_knowledge import DSN, PARSE, SPEC, isolated_store, public_corpus, stage

pytestmark = pytest.mark.skipif(not DSN, reason='requires explicitly isolated PG18.6 fixture')


def test_indexer_role_stages_verifies_reuses_and_activates_without_chunk_update_privilege() -> None:
    async def run() -> None:
        async with isolated_store() as (_, admin):
            assert DSN is not None
            scoped = PostgresDatabase(DSN)
            await scoped.open()
            await scoped.pool.resize(1, 1)
            try:
                async with scoped.pool.connection() as conn:
                    await conn.execute('SET ROLE pequeverso_knowledge_indexer')
                    row = await (
                        await conn.execute(
                            'SELECT current_user AS role,has_table_privilege(current_user,'
                            "'knowledge.chunks','UPDATE') AS can_update"
                        )
                    ).fetchone()
                    assert row is not None and row['role'] == 'pequeverso_knowledge_indexer'
                    assert row['can_update'] is False
                store = PostgresKnowledgeStore(scoped, PARSE, SPEC, 'knowledge-v1')
                value = public_corpus()
                # Do not hold the session indexing lock in the one-connection test pool:
                # the production indexer uses a dedicated owner plus a second pool connection.
                await stage(store, value)
                proof = await store.projection_stamp(value.revision.version)
                assert proof is not None
                await store.mark_prepared(value.revision.version, proof)
                vectors = await store.vectors_for_indexing(
                    value.revision.version, tuple(c.id for c in value.chunks)
                )
                await store.stage(value, vectors)
                await store.activate_prepared(value.revision.version)
                assert await store.active_revision() == value.revision
                async with admin.pool.connection() as conn:
                    row = await (
                        await conn.execute(
                            "SELECT has_table_privilege('pequeverso_knowledge_indexer',"
                            "'knowledge.chunks','UPDATE') AS can_update"
                        )
                    ).fetchone()
                    assert row is not None and row['can_update'] is False
            finally:
                await scoped.close()

    asyncio.run(run())
