import asyncio
from dataclasses import replace
from datetime import timedelta

import pytest

from app.application.knowledge import HybridKnowledgeRetrieval
from app.domain.catalog import ActiveCatalog
from app.domain.errors import FailureCode, RejectedError
from app.domain.knowledge import EmbeddingPurpose, KnowledgeHit, ProjectionStamp, RetrievalStrategy
from app.domain.language import Language
from tests.test_public_corpus import NOW, PARSE, PARSER_VERSION, SPEC, build


class Clock:
    def now(self):
        return NOW


class Embeddings:
    spec = SPEC

    def __init__(self):
        self.calls = []
        self.vector = (1.0,) + (0.0,) * 63

    async def encode(self, texts, purpose):
        self.calls.append((texts, purpose))
        return (self.vector,)


class Store:
    def __init__(self, corpus):
        self.corpus = corpus
        self.revision = corpus.revision
        self.lexical = ()
        self.vector = ()
        self.missing = set()
        self.path_valid = True
        self.verified_paths = []
        self.switch_after_read = False
        self.stamp = ProjectionStamp(
            self.revision.version,
            self.revision.catalog_sha256,
            len(corpus.chunks),
            len(corpus.entities),
            len(corpus.relations),
        )

    async def active_revision(self):
        return self.revision

    async def projection_stamp(self, version):
        assert version == self.corpus.revision.version
        return self.stamp

    async def lexical_candidates(self, version, question, limit):
        assert version == self.corpus.revision.version and limit == 12
        return self.lexical

    async def vector_candidates(self, version, vector, limit):
        assert version == self.corpus.revision.version and limit == 12
        return self.vector

    async def read_chunks(self, version, ids):
        assert version == self.corpus.revision.version
        if self.switch_after_read:
            self.revision = replace(self.revision, version='f' * 64)
        return tuple(c for c in self.corpus.chunks if c.id in ids and c.id not in self.missing)

    async def verify_relations(self, version, relations):
        self.verified_paths.append(relations)
        return self.path_valid and all(r in self.corpus.relations for r in relations)

    def hit(self, cid, strategy=RetrievalStrategy.LEXICAL, relations=()):
        c = next(c for c in self.corpus.chunks if c.id == cid)
        return KnowledgeHit(self.corpus.revision.version, cid, c.sha256, 0.5, strategy, relations)


class Graph:
    def __init__(self, stamp):
        self.stamp = stamp
        self.hits = ()
        self.error = None
        self.seeds = ()

    async def projection_stamp(self, version):
        if self.error:
            raise self.error
        return self.stamp

    async def candidates(self, version, supporting_chunk_ids, limit):
        self.seeds = supporting_chunk_ids
        return self.hits


def setup():
    corpus = build()
    store = Store(corpus)
    graph = Graph(store.stamp)
    embeddings = Embeddings()
    active = ActiveCatalog(PARSE(corpus.catalog_body), corpus.revision.catalog_sha256, NOW, timedelta(days=1))
    retrieval = HybridKnowledgeRetrieval(store, graph, embeddings, PARSER_VERSION, Clock())
    return retrieval, store, graph, embeddings, active


def execute(retrieval, active, products=(), question='¿Qué incluye?'):
    return asyncio.run(retrieval.retrieve(active, question, products, Language.ES))


def test_hybrid_uses_single_query_embedding_and_keeps_both_comparison_product_anchors() -> None:
    retrieval, store, _, embeddings, active = setup()
    store.lexical = (store.hit('product:grafismo-fonetico'),)
    store.vector = (store.hit('product:grafismo-fonetico', RetrievalStrategy.VECTOR),)
    result = execute(retrieval, active, ('grafismo-fonetico', 'alimentacion-bebe'), 'Compara ambos productos')
    assert {c.id for c in result.chunks} == {'product:grafismo-fonetico', 'product:alimentacion-bebe'}
    assert embeddings.calls == [(('Compara ambos productos',), EmbeddingPurpose.QUERY)]
    assert result.strategies == (RetrievalStrategy.LEXICAL, RetrievalStrategy.VECTOR)


def test_graph_finds_supported_two_hop_sibling_resource_and_verifies_pg_relations() -> None:
    retrieval, store, graph, _, active = setup()
    relations = tuple(r for r in store.corpus.relations if r.predicate == 'includes')[:2]
    first, second = (r.supporting_chunk_id for r in relations)
    store.lexical = (store.hit(first),)
    graph.hits = (store.hit(second, RetrievalStrategy.GRAPH, relations),)
    result = execute(retrieval, active, ('grafismo-fonetico',))
    assert second in {c.id for c in result.chunks}
    assert graph.seeds == (first,)
    assert store.verified_paths == [relations]
    assert RetrievalStrategy.GRAPH in result.strategies
    assert not result.graph_degraded


def test_one_hop_graph_path_is_supported_and_source_scoped() -> None:
    retrieval, store, graph, _, active = setup()
    relation = next(r for r in store.corpus.relations if r.predicate == 'includes')
    store.lexical = (store.hit('product:grafismo-fonetico'),)
    graph.hits = (store.hit(relation.supporting_chunk_id, RetrievalStrategy.GRAPH, (relation,)),)
    assert relation.supporting_chunk_id in {c.id for c in execute(retrieval, active).chunks}


def test_canonical_but_unrelated_graph_path_cannot_launder_a_different_chunk() -> None:
    retrieval, store, graph, _, active = setup()
    relation = next(r for r in store.corpus.relations if r.predicate == 'includes')
    store.lexical = (store.hit('product:grafismo-fonetico'),)
    graph.hits = (store.hit('product:alimentacion-bebe', RetrievalStrategy.GRAPH, (relation,)),)
    with pytest.raises(RejectedError, match='catalog_unavailable'):
        execute(retrieval, active)


@pytest.mark.parametrize('failure', ['missing_path', 'unsupported_path', 'foreign_version', 'foreign_hash'])
def test_unverified_graph_or_index_evidence_is_rejected(failure) -> None:
    retrieval, store, graph, _, active = setup()
    relation = next(r for r in store.corpus.relations if r.predicate == 'includes')
    store.lexical = (store.hit('product:grafismo-fonetico'),)
    hit = store.hit(relation.supporting_chunk_id, RetrievalStrategy.GRAPH, (relation,))
    if failure == 'missing_path':
        hit = replace(hit, relations=())
    elif failure == 'unsupported_path':
        store.path_valid = False
    elif failure == 'foreign_version':
        hit = replace(hit, version='f' * 64)
    else:
        hit = replace(hit, sha256='f' * 64)
    graph.hits = (hit,)
    with pytest.raises(RejectedError, match='catalog_unavailable'):
        execute(retrieval, active)


@pytest.mark.parametrize(
    'failure', ['stale', 'missing_version', 'parser', 'profile', 'catalog_hash', 'source']
)
def test_stale_or_incoherent_snapshot_is_rejected_before_embedding(failure) -> None:
    retrieval, store, _, embeddings, active = setup()
    if failure == 'stale':
        active = replace(active, verified_at=NOW - timedelta(days=2))
    elif failure == 'missing_version':
        store.revision = None
    elif failure == 'parser':
        store.revision = replace(store.revision, parser_version='other')
    elif failure == 'profile':
        embeddings.spec = replace(SPEC, provider='openai', model='text-embedding-3-small', dimensions=1536)
    elif failure == 'catalog_hash':
        active = replace(active, sha256='f' * 64)
    else:
        store.revision = replace(store.revision, source_revision='f' * 40)
    with pytest.raises(RejectedError, match='catalog_unavailable'):
        execute(retrieval, active)
    assert not embeddings.calls
    assert not asyncio.run(retrieval.ready(active))


def test_graph_outage_degrades_to_verified_pg_and_readiness_is_false() -> None:
    retrieval, store, graph, _, active = setup()
    store.lexical = (store.hit('product:grafismo-fonetico'),)
    graph.error = RejectedError(FailureCode.DEPENDENCY_UNAVAILABLE)
    result = execute(retrieval, active)
    assert result.graph_degraded
    assert result.chunks
    assert not asyncio.run(retrieval.ready(active))


def test_affiliate_selection_cannot_receive_core_policy_or_resource() -> None:
    retrieval, store, _, _, active = setup()
    core = tuple(c for c in store.corpus.chunks if c.product_ids == ('grafismo-fonetico',))[:12]
    store.lexical = tuple(store.hit(c.id) for c in core)
    result = execute(retrieval, active, ('alimentacion-bebe',))
    assert {c.id for c in result.chunks} == {'product:alimentacion-bebe'}


def test_comparison_missing_anchor_is_rejected_instead_of_looking_complete() -> None:
    retrieval, store, _, _, active = setup()
    store.missing.add('product:alimentacion-bebe')
    with pytest.raises(RejectedError, match='catalog_unavailable'):
        execute(retrieval, active, ('grafismo-fonetico', 'alimentacion-bebe'))


def test_activation_race_never_returns_mixed_version_evidence_or_retries() -> None:
    retrieval, store, _, embeddings, active = setup()
    store.lexical = (store.hit('product:grafismo-fonetico'),)
    store.switch_after_read = True
    with pytest.raises(RejectedError, match='catalog_unavailable'):
        execute(retrieval, active)
    assert len(embeddings.calls) == 1


@pytest.mark.parametrize(('question', 'products'), [('', ()), ('x' * 8001, ()), ('consulta', ('unknown',))])
def test_invalid_query_is_rejected_without_provider_work(question, products) -> None:
    retrieval, _, _, embeddings, active = setup()
    with pytest.raises(RejectedError, match='invalid_request'):
        execute(retrieval, active, products, question)
    assert not embeddings.calls
