"""Versioned public knowledge values; no provider, database or orchestration SDK types."""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

_SHA256 = re.compile(r'[a-f0-9]{64}\Z')
_REVISION = re.compile(r'[a-f0-9]{40}\Z')
MAX_PUBLIC_BODY_BYTES = 1_048_576
MAX_KNOWLEDGE_CHUNKS = 2048
MAX_KNOWLEDGE_ENTITIES = 4096
MAX_KNOWLEDGE_RELATIONS = 8192
MAX_CHUNK_TEXT_BYTES = 2_097_152


class EmbeddingPurpose(StrEnum):
    INDEX = 'index'
    QUERY = 'query'


@dataclass(frozen=True, slots=True)
class EmbeddingSpec:
    provider: str
    model: str
    dimensions: int

    def __post_init__(self) -> None:
        supported = {('fixture', 'hash64-v1', 64), ('openai', 'text-embedding-3-small', 1536)}
        if (self.provider, self.model, self.dimensions) not in supported:
            raise ValueError('unsupported embedding identity')


def validate_vector(values: tuple[float, ...], spec: EmbeddingSpec) -> None:
    if len(values) != spec.dimensions or any(not math.isfinite(value) for value in values):
        raise ValueError('embedding must match its declared dimensions and contain finite values')
    norm = math.hypot(*values)
    if not math.isfinite(norm) or norm == 0:
        raise ValueError('cosine embeddings require a finite nonzero norm')


@dataclass(frozen=True, slots=True)
class KnowledgeRevision:
    version: str
    catalog_sha256: str
    source_revision: str
    parser_version: str
    embedding: EmbeddingSpec

    def __post_init__(self) -> None:
        if not _SHA256.fullmatch(self.version) or not _SHA256.fullmatch(self.catalog_sha256):
            raise ValueError('knowledge fingerprints must be sha256 values')
        if not _REVISION.fullmatch(self.source_revision) or not self.parser_version:
            raise ValueError('knowledge requires an exact source revision and parser version')


class ChunkKind(StrEnum):
    PRODUCT = 'product'
    RESOURCE = 'resource'
    DOCUMENT = 'document'
    LINK = 'link'


@dataclass(frozen=True, slots=True)
class KnowledgeChunk:
    id: str
    kind: ChunkKind
    source_id: str
    title: str
    text: str
    url: str
    product_ids: tuple[str, ...]
    sha256: str
    source_pointer: str

    def __post_init__(self) -> None:
        if not self.id or not self.source_id or not self.source_pointer:
            raise ValueError('a chunk requires stable source identity')
        if not self.text or len(self.text.encode('utf-8')) > 8000:
            raise ValueError('a chunk must contain at most 8000 UTF-8 bytes')
        if hashlib.sha256(self.text.encode('utf-8')).hexdigest() != self.sha256:
            raise ValueError('chunk content hash mismatch')


class EntityKind(StrEnum):
    PRODUCT = 'product'
    RESOURCE = 'resource'
    DOCUMENT = 'document'
    LINK = 'link'
    TOPIC = 'topic'


@dataclass(frozen=True, slots=True)
class KnowledgeEntity:
    id: str
    kind: EntityKind
    label: str
    supporting_chunk_ids: tuple[str, ...]


class RelationKind(StrEnum):
    INCLUDES = 'includes'
    HAS_DOCUMENT = 'has_document'
    HAS_LINK = 'has_link'
    HAS_TOPIC = 'has_topic'


@dataclass(frozen=True, slots=True)
class KnowledgeRelation:
    subject_id: str
    predicate: RelationKind
    object_id: str
    supporting_chunk_id: str
    source_pointer: str


@dataclass(frozen=True, slots=True)
class KnowledgeCorpus:
    revision: KnowledgeRevision
    catalog_body: bytes
    verified_at: datetime
    chunks: tuple[KnowledgeChunk, ...]
    entities: tuple[KnowledgeEntity, ...]
    relations: tuple[KnowledgeRelation, ...]

    def __post_init__(self) -> None:
        if (
            len(self.catalog_body) > MAX_PUBLIC_BODY_BYTES
            or len(self.chunks) > MAX_KNOWLEDGE_CHUNKS
            or len(self.entities) > MAX_KNOWLEDGE_ENTITIES
            or len(self.relations) > MAX_KNOWLEDGE_RELATIONS
            or sum(len(chunk.text.encode('utf-8')) for chunk in self.chunks) > MAX_CHUNK_TEXT_BYTES
        ):
            raise ValueError('public knowledge exceeds its ingestion bounds')
        if hashlib.sha256(self.catalog_body).hexdigest() != self.revision.catalog_sha256:
            raise ValueError('catalog snapshot hash mismatch')
        ids = {chunk.id for chunk in self.chunks}
        if not ids or len(ids) != len(self.chunks):
            raise ValueError('knowledge chunks must be nonempty and uniquely identified')
        entities = {entity.id: entity for entity in self.entities}
        if (
            not entities
            or len(entities) != len(self.entities)
            or any(not entity.id for entity in self.entities)
        ):
            raise ValueError('knowledge entity ids must be nonempty and unique')
        if any(
            not entity.supporting_chunk_ids or not set(entity.supporting_chunk_ids).issubset(ids)
            for entity in self.entities
        ):
            raise ValueError('entity evidence must belong to this corpus')
        targets = {
            RelationKind.INCLUDES: EntityKind.RESOURCE,
            RelationKind.HAS_DOCUMENT: EntityKind.DOCUMENT,
            RelationKind.HAS_LINK: EntityKind.LINK,
            RelationKind.HAS_TOPIC: EntityKind.TOPIC,
        }
        if len(set(self.relations)) != len(self.relations):
            raise ValueError('knowledge relationships must be unique')
        if any(
            relation.subject_id not in entities
            or relation.object_id not in entities
            or relation.supporting_chunk_id not in ids
            or not relation.source_pointer
            or entities[relation.subject_id].kind is not EntityKind.PRODUCT
            or entities[relation.object_id].kind is not targets[relation.predicate]
            for relation in self.relations
        ):
            raise ValueError('relationship evidence must belong to this corpus')


@dataclass(frozen=True, slots=True)
class ProjectionStamp:
    version: str
    catalog_sha256: str
    chunk_count: int
    entity_count: int
    relation_count: int

    def __post_init__(self) -> None:
        if not _SHA256.fullmatch(self.version) or not _SHA256.fullmatch(self.catalog_sha256):
            raise ValueError('projections require exact knowledge fingerprints')
        for value, maximum in (
            (self.chunk_count, MAX_KNOWLEDGE_CHUNKS),
            (self.entity_count, MAX_KNOWLEDGE_ENTITIES),
            (self.relation_count, MAX_KNOWLEDGE_RELATIONS),
        ):
            if type(value) is not int or not 0 <= value <= maximum:
                raise ValueError('projection counts must be bounded nonnegative integers')


class RetrievalStrategy(StrEnum):
    LEXICAL = 'lexical'
    VECTOR = 'vector'
    GRAPH = 'graph'


@dataclass(frozen=True, slots=True)
class KnowledgeHit:
    version: str
    chunk_id: str
    sha256: str
    score: float
    strategy: RetrievalStrategy
    relations: tuple[KnowledgeRelation, ...] = ()

    def __post_init__(self) -> None:
        if not _SHA256.fullmatch(self.version) or not _SHA256.fullmatch(self.sha256):
            raise ValueError('retrieval hits require versioned content fingerprints')
        if not self.chunk_id or not math.isfinite(self.score):
            raise ValueError('retrieval hits require stable ids and finite scores')


@dataclass(frozen=True, slots=True)
class RetrievedKnowledge:
    revision: KnowledgeRevision
    chunks: tuple[KnowledgeChunk, ...]
    strategies: tuple[RetrievalStrategy, ...]
    graph_degraded: bool = False
