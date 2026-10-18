import asyncio

import pytest
from neo4j import Query
from neo4j.exceptions import ServiceUnavailable

from app.adapters.neo4j.public_graph import Neo4jPublicGraph
from app.domain.errors import RejectedError
from tests.test_public_corpus import build


class Result:
    def __init__(self, rows=()):
        self.rows = list(rows)

    async def consume(self):
        return None

    async def data(self):
        return self.rows


class Transaction:
    def __init__(self, driver):
        self.driver = driver

    async def __aenter__(self):
        return self

    async def __aexit__(self, kind, error, traceback):
        if error:
            self.driver.rollbacks += 1

    async def run(self, statement, **params):
        self.driver.calls.append((statement, params))
        if self.driver.fail_stage and 'PV_REL' in statement:
            raise ServiceUnavailable('synthetic private credential error must stay inside adapter')
        if 'RETURN chunks,entities' in statement:
            return Result([self.driver.counts])
        return Result()

    async def commit(self):
        self.driver.commits += 1


class Session:
    def __init__(self, driver):
        self.driver = driver

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        self.driver.session_exits += 1

    async def begin_transaction(self, **kwargs):
        assert kwargs == {'timeout': 15.0}
        return Transaction(self.driver)

    async def run(self, query, **params):
        assert isinstance(query, Query) and query.timeout == 2.0
        self.driver.calls.append((query.text, params))
        if self.driver.fail_read:
            raise ServiceUnavailable('synthetic private credential error must stay inside adapter')
        if 'RETURN chunks,entities' in query.text:
            return Result([self.driver.counts])
        if 'RETURN p.version' in query.text:
            return Result(self.driver.stamps)
        if 'MATCH path=' in query.text:
            return Result(self.driver.hits)
        return Result()


class Driver:
    def __init__(self):
        corpus = build()
        self.counts = {
            'chunks': len(corpus.chunks),
            'entities': len(corpus.entities),
            'relations': len(corpus.relations),
        }
        self.stamps = [
            {'version': corpus.revision.version, 'sha256': corpus.revision.catalog_sha256, **self.counts}
        ]
        self.calls = []
        self.commits = 0
        self.rollbacks = 0
        self.session_exits = 0
        self.fail_stage = False
        self.fail_read = False
        self.hits = []

    def session(self, *, database):
        assert database == 'neo4j'
        return Session(self)


def test_stage_has_one_atomic_transaction_bound_params_and_never_closes_borrowed_driver() -> None:
    driver = Driver()
    corpus = build()
    asyncio.run(Neo4jPublicGraph(driver).stage(corpus))
    assert driver.commits == 1 and driver.rollbacks == 0 and driver.session_exits == 1
    constraints = [query for query, _ in driver.calls if query.startswith('CREATE CONSTRAINT')]
    assert len(constraints) == 3 and all('IF NOT EXISTS' in q for q in constraints)
    delete = next(params for query, params in driver.calls if 'DETACH DELETE' in query)
    assert delete == {'version': corpus.revision.version}
    chunks = next(p['rows'] for query, p in driver.calls if 'CREATE (:PVChunk' in query)
    assert len(chunks) == len(corpus.chunks)
    assert all(set(row) == {'id', 'sha256'} for row in chunks)
    # No raw catalog bodies, visitor text, embeddings, prompts or secrets live in graph chunks.
    assert corpus.catalog_body.decode() not in repr(driver.calls)


def test_partial_projection_rolls_back_and_never_publishes_a_stamp() -> None:
    driver = Driver()
    driver.counts['chunks'] = 0
    with pytest.raises(ValueError, match='counts do not match'):
        asyncio.run(Neo4jPublicGraph(driver).stage(build()))
    assert driver.commits == 0 and driver.rollbacks == 1
    assert not any(query.startswith('CREATE (:PVProjection') for query, _ in driver.calls)


def test_driver_failure_during_stage_is_safe_and_rolls_back_without_retry() -> None:
    driver = Driver()
    driver.fail_stage = True
    with pytest.raises(RejectedError, match=r'^dependency_unavailable$'):
        asyncio.run(Neo4jPublicGraph(driver).stage(build()))
    assert driver.commits == 0 and driver.rollbacks == 1
    assert len([query for query, _ in driver.calls if 'DETACH DELETE' in query]) == 1


def test_projection_stamp_verifies_actual_counts_and_missing_is_not_ready() -> None:
    driver = Driver()
    graph = Neo4jPublicGraph(driver)
    stamp = asyncio.run(graph.projection_stamp(build().revision.version))
    assert stamp.chunk_count == len(build().chunks)
    driver.counts['entities'] = 0
    assert asyncio.run(graph.projection_stamp(build().revision.version)) is None
    driver.stamps = []
    assert asyncio.run(graph.projection_stamp(build().revision.version)) is None


def test_graph_candidates_are_fixed_two_hop_queries_with_bound_ids_and_explicit_provenance() -> None:
    driver = Driver()
    corpus = build()
    relation = next(r for r in corpus.relations if r.predicate == 'includes')
    chunk = next(c for c in corpus.chunks if c.id == relation.supporting_chunk_id)
    driver.hits = [
        {
            'id': chunk.id,
            'sha256': chunk.sha256,
            'depth': 1,
            'relations': [
                {
                    'subject': relation.subject_id,
                    'object': relation.object_id,
                    'predicate': relation.predicate.value,
                    'support': chunk.id,
                    'pointer': relation.source_pointer,
                }
            ],
        }
    ]
    malicious_id = "product:x'}) DETACH DELETE n //"
    hits = asyncio.run(Neo4jPublicGraph(driver).candidates(corpus.revision.version, (malicious_id,), 4))
    assert hits[0].relations == (relation,)
    query, params = driver.calls[-1]
    assert malicious_id not in query
    assert params['supports'] == [malicious_id] and params['limit'] == 4
    assert 'PV_REL*1..2' in query and 'LIMIT 24' in query and 'LIMIT 96' in query and 'LIMIT $limit' in query
    assert 'apoc.' not in query.lower()


@pytest.mark.parametrize('failure', ['empty_relations', 'long_path', 'unknown_predicate', 'missing_pointer'])
def test_malformed_graph_provenance_is_rejected(failure) -> None:
    driver = Driver()
    relation = next(r for r in build().relations if r.predicate == 'includes')
    edge = {
        'subject': relation.subject_id,
        'object': relation.object_id,
        'predicate': relation.predicate.value,
        'support': relation.supporting_chunk_id,
        'pointer': relation.source_pointer,
    }
    row = {'id': relation.supporting_chunk_id, 'sha256': 'a' * 64, 'depth': 1, 'relations': [edge]}
    if failure == 'empty_relations':
        row['relations'] = []
    elif failure == 'long_path':
        row['depth'] = 3
    elif failure == 'unknown_predicate':
        edge['predicate'] = 'guarantees_health'
    else:
        edge.pop('pointer')
    driver.hits = [row]
    with pytest.raises(ValueError, match=r'provenance|supported edges|valid RelationKind'):
        asyncio.run(Neo4jPublicGraph(driver).candidates(build().revision.version, ('product:test',), 4))


@pytest.mark.parametrize(('limit', 'seeds'), [(0, ()), (13, ()), (1, ('x',) * 13)])
def test_candidate_bounds_are_enforced_before_driver_work(limit, seeds) -> None:
    driver = Driver()
    with pytest.raises(ValueError, match='bounded'):
        asyncio.run(Neo4jPublicGraph(driver).candidates(build().revision.version, seeds, limit))
    assert not driver.calls


def test_safe_driver_error_never_exposes_bolt_exception_message_or_retries() -> None:
    driver = Driver()
    driver.fail_read = True
    with pytest.raises(RejectedError, match=r'^dependency_unavailable$'):
        asyncio.run(Neo4jPublicGraph(driver).projection_stamp(build().revision.version))
    assert len(driver.calls) == 1
