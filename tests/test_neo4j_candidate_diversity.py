import asyncio

import pytest

from app.adapters.neo4j.public_graph import Neo4jPublicGraph
from tests.test_neo4j_public_graph import Driver
from tests.test_neo4j_public_graph_live_service import URI, connect
from tests.test_public_corpus import build


def test_adapter_rejects_duplicate_chunk_rows_instead_of_spending_diversity_limit():
    driver = Driver()
    corpus = build()
    relation = corpus.relations[0]
    chunk = next(c for c in corpus.chunks if c.id == relation.supporting_chunk_id)
    row = {
        'id': chunk.id,
        'sha256': chunk.sha256,
        'depth': 1,
        'relations': [
            {
                'subject': relation.subject_id,
                'predicate': relation.predicate.value,
                'object': relation.object_id,
                'support': relation.supporting_chunk_id,
                'pointer': relation.source_pointer,
            }
        ],
    }
    driver.hits = [row, row]
    with pytest.raises(ValueError, match='duplicate'):
        asyncio.run(Neo4jPublicGraph(driver).candidates(corpus.revision.version, (chunk.id,), 12))


@pytest.mark.skipif(not URI, reason='dedicated isolated Bolt fixture not requested')
def test_real_bolt_multiple_supported_paths_return_distinct_targets_before_limit():
    async def run():
        driver = connect()
        try:
            corpus = build()
            graph = Neo4jPublicGraph(driver)
            # Reuse the current complete projection without staging or modifying fixture state.
            assert await graph.projection_stamp(corpus.revision.version) is not None
            seeds = tuple(r.supporting_chunk_id for r in corpus.relations if r.predicate == 'includes')[:4]
            hits = await graph.candidates(corpus.revision.version, seeds, 12)
            assert len(hits) == 12
            assert len({hit.chunk_id for hit in hits}) == 12
            assert all(relation in corpus.relations for hit in hits for relation in hit.relations)
            assert hits == await graph.candidates(corpus.revision.version, seeds, 12)
        finally:
            await driver.close()

    asyncio.run(run())
