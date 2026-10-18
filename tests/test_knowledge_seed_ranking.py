from types import MethodType

import pytest

from app.domain.knowledge import RetrievalStrategy
from tests.test_hybrid_knowledge import execute, setup


@pytest.mark.parametrize('reverse_storage', [False, True])
def test_graph_seeds_follow_verified_fusion_rank_not_canonical_storage_order(reverse_storage):
    retrieval, store, graph, _, active = setup()
    chunks = store.corpus.chunks[:24]
    assert len(chunks) == 24
    store.lexical = tuple(store.hit(c.id) for c in reversed(chunks[12:]))
    store.vector = tuple(store.hit(c.id, RetrievalStrategy.VECTOR) for c in chunks[:12])

    async def read_chunks(self, version, ids):
        assert version == self.corpus.revision.version
        ordered = reversed(self.corpus.chunks) if reverse_storage else self.corpus.chunks
        return tuple(c for c in ordered if c.id in ids)

    store.read_chunks = MethodType(read_chunks, store)
    execute(retrieval, active)
    scores = {
        hit.chunk_id: weight / (rank + 1)
        for hits, weight in ((store.lexical, 1.0), (store.vector, 0.8))
        for rank, hit in enumerate(hits)
    }
    expected = tuple(sorted(scores, key=lambda cid: (-scores[cid], cid)))[:12]
    assert graph.seeds == expected
    assert graph.seeds[0] == store.lexical[0].chunk_id
    assert len(graph.seeds) == len(set(graph.seeds)) == 12
