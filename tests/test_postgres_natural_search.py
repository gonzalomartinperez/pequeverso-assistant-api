"""Natural-language framing must not turn a literal catalog match into an empty AND query."""

import asyncio

import pytest

from tests.test_postgres_knowledge import DSN, isolated_store, public_corpus, stage

pytestmark = pytest.mark.skipif(not DSN, reason='requires explicitly isolated real PG18.6/pgvector0.8.7')


@pytest.mark.parametrize(
    'question',
    [
        'Por favor, quisiera información sobre Grafismo Fonético, ¿me orientas?',
        'Could you please tell me about Grafismo Fonético?',
        'Grafismo -Fonético',
    ],
)
def test_natural_framing_retains_catalog_keyword_matches(question: str) -> None:
    async def run() -> None:
        async with isolated_store() as (store, _):
            corpus = public_corpus()
            await stage(store, corpus)
            hits = await store.lexical_candidates(corpus.revision.version, question, 4)
            assert 'product:grafismo-fonetico' in {hit.chunk_id for hit in hits}
            assert all(hit.version == corpus.revision.version for hit in hits)

    asyncio.run(run())


def test_search_ignores_boolean_syntax_and_cannot_change_catalog_or_escape_version() -> None:
    async def run() -> None:
        async with isolated_store() as (store, db):
            corpus = public_corpus()
            await stage(store, corpus)
            question = "' OR 1=1; DROP SCHEMA knowledge CASCADE; -- Grafismo"
            hits = await store.lexical_candidates(corpus.revision.version, question, 1)
            assert len(hits) == 1 and hits[0].chunk_id == 'product:grafismo-fonetico'
            assert await store.lexical_candidates('f' * 64, question, 4) == ()
            assert await store.lexical_candidates(corpus.revision.version, 'de y la the and', 4) == ()
            assert await store.lexical_candidates(corpus.revision.version, 'x' * 8001, 4) == ()
            async with db.pool.connection() as connection:
                row = await (
                    await connection.execute('SELECT count(*) AS n FROM knowledge.chunks')
                ).fetchone()
                assert row is not None and row['n'] == len(corpus.chunks)

    asyncio.run(run())
