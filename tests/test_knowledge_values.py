import hashlib
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from app.domain.knowledge import (
    MAX_PUBLIC_BODY_BYTES,
    ChunkKind,
    EmbeddingSpec,
    EntityKind,
    KnowledgeChunk,
    KnowledgeCorpus,
    KnowledgeEntity,
    KnowledgeHit,
    KnowledgeRelation,
    KnowledgeRevision,
    ProjectionStamp,
    RelationKind,
    RetrievalStrategy,
    validate_vector,
)


def corpus() -> KnowledgeCorpus:
    body = b'{}'
    text = 'Published product resource.'
    chunk = KnowledgeChunk(
        'resource:sample',
        ChunkKind.RESOURCE,
        'sample',
        'Resource',
        text,
        'https://pequeverso.com/grafismo-fonetico/',
        ('kit',),
        hashlib.sha256(text.encode()).hexdigest(),
        '/products/0/resources/0',
    )
    revision = KnowledgeRevision(
        'b' * 64,
        hashlib.sha256(body).hexdigest(),
        'a' * 40,
        'knowledge-v1',
        EmbeddingSpec('fixture', 'hash64-v1', 64),
    )
    return KnowledgeCorpus(
        revision,
        body,
        datetime.now(UTC),
        (chunk,),
        (
            KnowledgeEntity('product:kit', EntityKind.PRODUCT, 'Kit', (chunk.id,)),
            KnowledgeEntity('resource:sample', EntityKind.RESOURCE, 'Resource', (chunk.id,)),
        ),
        (
            KnowledgeRelation(
                'product:kit', RelationKind.INCLUDES, 'resource:sample', chunk.id, '/products/0/resources/0'
            ),
        ),
    )


def test_valid_public_corpus_and_nonzero_fixture_vector() -> None:
    value = corpus()
    assert len(value.entities) == 2
    validate_vector((1.0,) + (0.0,) * 63, value.revision.embedding)


@pytest.mark.parametrize('values', [(), (0.0,) * 64, (float('nan'),) * 64, (float('inf'),) * 64])
def test_invalid_cosine_vectors_are_rejected(values: tuple[float, ...]) -> None:
    with pytest.raises(ValueError, match='embedding'):
        validate_vector(values, EmbeddingSpec('fixture', 'hash64-v1', 64))


@pytest.mark.parametrize(
    'spec',
    [
        ('openai', 'hash64-v1', 64),
        ('fixture', 'text-embedding-3-small', 1536),
        ('openai', 'text-embedding-3-small', 64),
        ('openai', 'other', 1536),
    ],
)
def test_embedding_identity_cannot_mix_modes_or_dimensions(spec: tuple[str, str, int]) -> None:
    with pytest.raises(ValueError, match='unsupported embedding identity'):
        EmbeddingSpec(*spec)


def test_catalog_and_chunk_hashes_must_match_actual_bytes() -> None:
    value = corpus()
    with pytest.raises(ValueError, match='catalog snapshot hash'):
        replace(value, catalog_body=b'{"different":true}')
    with pytest.raises(ValueError, match='chunk content hash'):
        replace(value.chunks[0], text='Modified evidence')


def test_chunk_limit_counts_utf8_bytes_without_truncating_evidence() -> None:
    with pytest.raises(ValueError, match='8000 UTF-8 bytes'):
        replace(corpus().chunks[0], text='á' * 4001)


def test_empty_or_foreign_entity_evidence_is_rejected() -> None:
    value = corpus()
    for support in [(), ('missing-chunk',)]:
        with pytest.raises(ValueError, match='entity evidence'):
            replace(
                value, entities=(replace(value.entities[0], supporting_chunk_ids=support), value.entities[1])
            )


@pytest.mark.parametrize(
    'predicate', [RelationKind.HAS_TOPIC, RelationKind.HAS_DOCUMENT, RelationKind.HAS_LINK]
)
def test_relation_target_kind_must_match_authorized_commercial_field(predicate: RelationKind) -> None:
    value = corpus()
    with pytest.raises(ValueError, match='relationship evidence'):
        replace(value, relations=(replace(value.relations[0], predicate=predicate),))


def test_missing_subject_foreign_support_and_duplicate_relations_are_rejected() -> None:
    value = corpus()
    for changes in [{'subject_id': 'missing'}, {'supporting_chunk_id': 'missing'}, {'source_pointer': ''}]:
        with pytest.raises(ValueError, match='relationship evidence'):
            replace(value, relations=(replace(value.relations[0], **changes),))
    with pytest.raises(ValueError, match='unique'):
        replace(value, relations=value.relations * 2)


def test_public_ingestion_is_bounded_before_staging() -> None:
    with pytest.raises(ValueError, match='ingestion bounds'):
        replace(corpus(), catalog_body=b'x' * (MAX_PUBLIC_BODY_BYTES + 1))


@pytest.mark.parametrize('count', [-1, True, 100000])
def test_projection_counts_reject_negative_boolean_or_unbounded_values(count: int) -> None:
    with pytest.raises(ValueError, match='projection counts'):
        ProjectionStamp('b' * 64, 'c' * 64, count, 2, 1)


def test_hit_fingerprints_and_scores_are_not_trusted() -> None:
    with pytest.raises(ValueError, match='fingerprints'):
        KnowledgeHit('old-version', 'chunk', 'a' * 64, 1.0, RetrievalStrategy.GRAPH)
    with pytest.raises(ValueError, match='finite scores'):
        KnowledgeHit('b' * 64, 'chunk', 'a' * 64, float('nan'), RetrievalStrategy.VECTOR)
