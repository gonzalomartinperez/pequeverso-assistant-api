"""Rebuildable, project-isolated public projection; PostgreSQL remains authoritative.

Neo4j Community READ routing is not authorization. Bootstrap owns the driver and
operators must isolate this instance/credentials/network from private data and other apps.
"""

from __future__ import annotations

from collections.abc import Mapping

from neo4j import AsyncDriver, Query
from neo4j.exceptions import DriverError, Neo4jError

from app.domain.errors import FailureCode, RejectedError
from app.domain.knowledge import (
    KnowledgeCorpus,
    KnowledgeHit,
    KnowledgeRelation,
    ProjectionStamp,
    RelationKind,
    RetrievalStrategy,
)

_CONSTRAINTS = (
    'CREATE CONSTRAINT pv_chunk_version_id IF NOT EXISTS FOR (n:PVChunk) REQUIRE (n.version,n.id) IS UNIQUE',
    'CREATE CONSTRAINT pv_entity_version_id IF NOT EXISTS FOR (n:PVEntity) REQUIRE (n.version,n.id) IS UNIQUE',
    'CREATE CONSTRAINT pv_projection_version IF NOT EXISTS FOR (n:PVProjection) REQUIRE n.version IS UNIQUE',
)
_DELETE = """MATCH (n) WHERE (n:PVChunk OR n:PVEntity OR n:PVProjection) AND n.version=$version
DETACH DELETE n"""
_CHUNKS = """UNWIND $rows AS row
CREATE (:PVChunk {version:$version,id:row.id,sha256:row.sha256})"""
_ENTITIES = """UNWIND $rows AS row
CREATE (:PVEntity {version:$version,id:row.id,kind:row.kind,label:row.label,supports:row.supports})"""
_RELATIONS = """UNWIND $rows AS row
MATCH (a:PVEntity {version:$version,id:row.subject}), (b:PVEntity {version:$version,id:row.object})
CREATE (a)-[:PV_REL {version:$version,predicate:row.predicate,
support:row.support,pointer:row.pointer}]->(b)"""
_STAMP = """CREATE (:PVProjection {version:$version,catalog_sha256:$sha256,
chunk_count:$chunk_count,entity_count:$entity_count,relation_count:$relation_count})"""
_COUNTS = """OPTIONAL MATCH (c:PVChunk {version:$version})
WITH count(c) AS chunks
OPTIONAL MATCH (e:PVEntity {version:$version})
WITH chunks,count(e) AS entities
OPTIONAL MATCH ()-[r:PV_REL {version:$version}]->()
RETURN chunks,entities,count(r) AS relations"""
_READ_STAMP = """MATCH (p:PVProjection {version:$version})
RETURN p.version AS version,p.catalog_sha256 AS sha256,
p.chunk_count AS chunks,p.entity_count AS entities,p.relation_count AS relations"""
# All paths are bounded and driven solely by verified chunk ids, never query text.
# Limit the deterministic anchor set before expansion to bound work for shared topics.
_CANDIDATES = """MATCH (s:PVEntity {version:$version})
WHERE any(id IN s.supports WHERE id IN $supports)
WITH s ORDER BY s.id LIMIT 24
MATCH path=(s)-[:PV_REL*1..2]-(t:PVEntity {version:$version})
WHERE all(r IN relationships(path) WHERE r.version=$version)
WITH t,path ORDER BY length(path),t.id,
[n IN nodes(path) | n.id],[r IN relationships(path) | r.pointer] LIMIT 96
UNWIND t.supports AS cid
MATCH (c:PVChunk {version:$version,id:cid})
WITH c,path ORDER BY length(path),c.id,
[n IN nodes(path) | n.id],[r IN relationships(path) | r.pointer]
WITH c,head(collect(path)) AS path
RETURN c.id AS id,c.sha256 AS sha256,length(path) AS depth,
[r IN relationships(path) | {subject:startNode(r).id,predicate:r.predicate,
object:endNode(r).id,support:r.support,pointer:r.pointer}] AS relations
ORDER BY depth,id LIMIT $limit"""


class Neo4jPublicGraph:
    def __init__(self, driver: AsyncDriver, database: str = 'neo4j', timeout_seconds: float = 2.0) -> None:
        if not database or not 0.1 <= timeout_seconds <= 5.0:
            raise ValueError('graph database and bounded timeout are required')
        self._driver = driver  # Borrowed. Only the composition root closes it.
        self._database = database
        self._timeout = timeout_seconds

    async def stage(self, corpus: KnowledgeCorpus) -> None:
        version = corpus.revision.version
        try:
            async with self._driver.session(database=self._database) as session:
                for statement in _CONSTRAINTS:
                    result = await session.run(Query(statement, timeout=self._timeout))
                    await result.consume()
                # Explicit transaction avoids execute_write's automatic retry behavior.
                async with await session.begin_transaction(timeout=15.0) as tx:
                    result = await tx.run(_DELETE, version=version)
                    await result.consume()
                    for statement, rows in (
                        (_CHUNKS, [{'id': c.id, 'sha256': c.sha256} for c in corpus.chunks]),
                        (
                            _ENTITIES,
                            [
                                {
                                    'id': e.id,
                                    'kind': e.kind.value,
                                    'label': e.label,
                                    'supports': list(e.supporting_chunk_ids),
                                }
                                for e in corpus.entities
                            ],
                        ),
                        (
                            _RELATIONS,
                            [
                                {
                                    'subject': r.subject_id,
                                    'object': r.object_id,
                                    'predicate': r.predicate.value,
                                    'support': r.supporting_chunk_id,
                                    'pointer': r.source_pointer,
                                }
                                for r in corpus.relations
                            ],
                        ),
                    ):
                        result = await tx.run(statement, version=version, rows=rows)
                        await result.consume()
                    result = await tx.run(_COUNTS, version=version)
                    rows = await result.data()
                    if len(rows) != 1 or self._counts(rows[0]) != (
                        len(corpus.chunks),
                        len(corpus.entities),
                        len(corpus.relations),
                    ):
                        raise ValueError('graph projection counts do not match the public corpus')
                    result = await tx.run(
                        _STAMP,
                        version=version,
                        sha256=corpus.revision.catalog_sha256,
                        chunk_count=len(corpus.chunks),
                        entity_count=len(corpus.entities),
                        relation_count=len(corpus.relations),
                    )
                    await result.consume()
                    await tx.commit()
        except (DriverError, Neo4jError, OSError, TimeoutError):
            raise RejectedError(FailureCode.DEPENDENCY_UNAVAILABLE) from None

    async def projection_stamp(self, version: str) -> ProjectionStamp | None:
        try:
            async with self._driver.session(database=self._database) as session:
                result = await session.run(Query(_READ_STAMP, timeout=self._timeout), version=version)
                rows = await result.data()
                if not rows:
                    return None
                if len(rows) != 1:
                    raise ValueError('graph projection stamp must be unique')
                row = rows[0]
                stamp = ProjectionStamp(
                    self._text(row, 'version'), self._text(row, 'sha256'), *self._counts(row)
                )
                # Metadata alone does not prove a complete projection after external damage.
                result = await session.run(Query(_COUNTS, timeout=self._timeout), version=version)
                counts = await result.data()
                if len(counts) != 1 or self._counts(counts[0]) != (
                    stamp.chunk_count,
                    stamp.entity_count,
                    stamp.relation_count,
                ):
                    return None
                return stamp
        except (DriverError, Neo4jError, OSError, TimeoutError):
            raise RejectedError(FailureCode.DEPENDENCY_UNAVAILABLE) from None

    async def candidates(
        self,
        version: str,
        supporting_chunk_ids: tuple[str, ...],
        limit: int,
    ) -> tuple[KnowledgeHit, ...]:
        if not 1 <= limit <= 12 or len(supporting_chunk_ids) > 12:
            raise ValueError('graph candidates must remain bounded')
        if not supporting_chunk_ids:
            return ()
        try:
            async with self._driver.session(database=self._database) as session:
                result = await session.run(
                    Query(_CANDIDATES, timeout=self._timeout),
                    version=version,
                    supports=list(supporting_chunk_ids),
                    limit=limit,
                )
                rows = await result.data()
            if len(rows) > limit:
                raise ValueError('graph returned more candidates than requested')
            hits: list[KnowledgeHit] = []
            seen: set[str] = set()
            for row in rows:
                chunk_id = self._text(row, 'id')
                if chunk_id in seen:
                    raise ValueError('graph returned duplicate chunk candidates')
                seen.add(chunk_id)
                depth = row.get('depth')
                relations = row.get('relations')
                if type(depth) is not int or not 1 <= depth <= 2 or not isinstance(relations, list):
                    raise ValueError('graph path must have one or two supported edges')
                if len(relations) != depth:
                    raise ValueError('graph path provenance is incomplete')
                path: list[KnowledgeRelation] = []
                for relation in relations:
                    if not isinstance(relation, dict):
                        raise TypeError('graph path provenance is malformed')
                    path.append(
                        KnowledgeRelation(
                            self._text(relation, 'subject'),
                            RelationKind(self._text(relation, 'predicate')),
                            self._text(relation, 'object'),
                            self._text(relation, 'support'),
                            self._text(relation, 'pointer'),
                        )
                    )
                hits.append(
                    KnowledgeHit(
                        version,
                        chunk_id,
                        self._text(row, 'sha256'),
                        1.0 / depth,
                        RetrievalStrategy.GRAPH,
                        tuple(path),
                    )
                )
            return tuple(hits)
        except (DriverError, Neo4jError, OSError, TimeoutError):
            raise RejectedError(FailureCode.DEPENDENCY_UNAVAILABLE) from None

    @staticmethod
    def _text(row: Mapping[str, object], key: str) -> str:
        value = row.get(key)
        if not isinstance(value, str) or not value:
            raise ValueError('graph returned invalid public provenance')
        return value

    @staticmethod
    def _counts(row: Mapping[str, object]) -> tuple[int, int, int]:
        return (
            Neo4jPublicGraph._count(row.get('chunks')),
            Neo4jPublicGraph._count(row.get('entities')),
            Neo4jPublicGraph._count(row.get('relations')),
        )

    @staticmethod
    def _count(value: object) -> int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise TypeError('graph returned invalid projection counts')
        if value < 0:
            raise ValueError('graph returned invalid projection counts')
        return value
