import asyncio

import pytest

from app.application.knowledge_evaluation import FixtureKnowledgeEvaluator
from app.domain.errors import RejectedError
from app.domain.knowledge import EmbeddingSpec
from tests.test_hybrid_knowledge import setup


def evaluator():
    retrieval, store, graph, embeddings, active = setup()
    store.lexical = (store.hit('product:grafismo-fonetico'),)
    evaluation = FixtureKnowledgeEvaluator(store, graph, embeddings, retrieval, active, store.revision)
    return evaluation, store, graph, embeddings


def test_relevance_labels_never_enter_search_query_vectors_scope_or_graph_seeds() -> None:
    evaluation, _, graph, embeddings = evaluator()
    first = asyncio.run(evaluation.evaluate('Grafismo Fonético', ('product:grafismo-fonetico',)))
    first_seeds = graph.seeds
    second = asyncio.run(evaluation.evaluate('Grafismo Fonético', ('product:alimentacion-bebe',)))
    assert first.actual_product_scope == second.actual_product_scope == ('grafismo-fonetico',)
    assert first_seeds == graph.seeds == ('product:grafismo-fonetico',)
    assert [tuple(c.id for c in s.chunks) for s in first.observations] == [
        tuple(c.id for c in s.chunks) for s in second.observations
    ]
    assert all(texts == ('Grafismo Fonético',) for texts, _ in embeddings.calls)
    assert first.observations[0].relevant_hit is True
    assert second.observations[0].relevant_hit is False


def test_strategy_labels_explicitly_distinguish_hash_vectors_and_lexical_seeded_graph() -> None:
    evaluation, _, _, _ = evaluator()
    result = asyncio.run(evaluation.evaluate('Grafismo Fonético', ()))
    assert [s.strategy for s in result.observations] == [
        'lexical',
        'vector_hash64_fixture',
        'graph_lexical_seeded',
        'hybrid',
    ]
    assert all(s.source_recall is None and s.relevant_hit is None for s in result.observations)


def test_component_comparison_refuses_a_real_embedding_provider_before_work() -> None:
    retrieval, store, graph, embeddings, active = setup()
    embeddings.spec = EmbeddingSpec('openai', 'text-embedding-3-small', 1536)
    with pytest.raises(ValueError, match='synthetic fixtures only'):
        FixtureKnowledgeEvaluator(store, graph, embeddings, retrieval, active, store.revision)
    assert not embeddings.calls


def test_known_projection_failure_stops_fixture_comparison_before_vector_work() -> None:
    evaluation, _, graph, embeddings = evaluator()
    graph.stamp = None
    with pytest.raises(RejectedError, match='dependency_unavailable'):
        asyncio.run(evaluation.evaluate('Grafismo Fonético', ('product:grafismo-fonetico',)))
    assert not embeddings.calls
