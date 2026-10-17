"""Real isolated Bolt fixture. No provider calls or paid model/embedding requests.

The smoke runner supplies only loopback coordinates and a synthetic service password.
This is not a live-model evaluation; default developer/CI runs skip an absent service.
"""

import asyncio
import json
import os

import pytest
from neo4j import AsyncGraphDatabase

from app.adapters.neo4j import public_graph
from app.adapters.neo4j.public_graph import Neo4jPublicGraph
from app.domain.errors import RejectedError
from tests.test_public_corpus import build

URI = os.environ.get('PV_TEST_NEO4J_URI', '')
pytestmark = pytest.mark.skipif(not URI, reason='isolated Neo4j fixture service not requested')


def connect():
    if URI != 'bolt://127.0.0.1:17689':
        raise ValueError('real graph fixtures require their dedicated loopback service')
    return AsyncGraphDatabase.driver(
        URI,
        auth=('neo4j', os.environ['PV_TEST_NEO4J_PASSWORD']),
        max_transaction_retry_time=0,
        connection_timeout=3,
        max_connection_pool_size=1,
    )


def test_real_bolt_projection_is_idempotent_and_returns_explicit_two_hop_paths() -> None:
    async def run():
        driver = connect()
        try:
            graph = Neo4jPublicGraph(driver)
            corpus = build()
            await graph.stage(corpus)
            first = await graph.projection_stamp(corpus.revision.version)
            await graph.stage(corpus)
            assert await graph.projection_stamp(corpus.revision.version) == first
            assert first.chunk_count == len(corpus.chunks)
            relations = tuple(r for r in corpus.relations if r.predicate == 'includes')
            seed = relations[0].supporting_chunk_id
            hits = await graph.candidates(corpus.revision.version, (seed,), 12)
            assert hits
            assert any(len(hit.relations) == 2 for hit in hits)
            assert all(relation in corpus.relations for hit in hits for relation in hit.relations)
            assert all(hit.version == corpus.revision.version for hit in hits)
        finally:
            await driver.close()

    asyncio.run(run())


def test_real_bolt_stage_failure_rolls_back_to_the_previous_complete_projection(monkeypatch) -> None:
    async def run():
        driver = connect()
        try:
            graph = Neo4jPublicGraph(driver)
            corpus = build()
            await graph.stage(corpus)
            previous = await graph.projection_stamp(corpus.revision.version)
            with monkeypatch.context() as patch:
                patch.setattr(public_graph, '_STAMP', 'SYNTHETIC INVALID CYPHER STATEMENT')
                with pytest.raises(RejectedError, match='dependency_unavailable'):
                    await graph.stage(corpus)
            assert await graph.projection_stamp(corpus.revision.version) == previous
        finally:
            await driver.close()

    asyncio.run(run())


def test_real_bolt_versions_are_isolated_and_tampering_invalidates_the_projection_stamp() -> None:
    async def run():
        driver = connect()
        try:
            graph = Neo4jPublicGraph(driver)
            original = build()
            raw = json.loads(original.catalog_body)
            raw['products'][0]['summary'] += ' Fixture-only public revision.'
            candidate = build(json.dumps(raw).encode())
            await graph.stage(original)
            await graph.stage(candidate)
            original_stamp = await graph.projection_stamp(original.revision.version)
            assert original_stamp and await graph.projection_stamp(candidate.revision.version)
            async with driver.session(database='neo4j') as session:
                result = await session.run(
                    'MATCH (c:PVChunk {version:$version}) WITH c LIMIT 1 DELETE c',
                    version=candidate.revision.version,
                )
                await result.consume()
            assert await graph.projection_stamp(candidate.revision.version) is None
            assert await graph.projection_stamp(original.revision.version) == original_stamp
            await graph.stage(candidate)
            assert await graph.projection_stamp(candidate.revision.version)
        finally:
            await driver.close()

    asyncio.run(run())


def test_real_bolt_existing_projection_is_verified_without_reindexing() -> None:
    """The smoke runner executes this alone immediately after dump/load, before any stage."""

    async def run():
        driver = connect()
        try:
            corpus = build()
            stamp = await Neo4jPublicGraph(driver).projection_stamp(corpus.revision.version)
            assert stamp is not None
            assert stamp.catalog_sha256 == corpus.revision.catalog_sha256
            assert stamp.chunk_count == len(corpus.chunks)
            assert stamp.entity_count == len(corpus.entities)
            assert stamp.relation_count == len(corpus.relations)
        finally:
            await driver.close()

    asyncio.run(run())
