import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.adapters.catalog.knowledge import PARSER_VERSION, build_public_corpus
from app.adapters.catalog_schema import CatalogParser
from app.domain.knowledge import EmbeddingSpec, EntityKind, RelationKind

BODY = Path('catalog/catalog.v1.json').read_bytes()
SPEC = EmbeddingSpec('fixture', 'hash64-v1', 64)
NOW = datetime(2026, 10, 17, tzinfo=UTC)
PARSE = CatalogParser(
    frozenset(
        {
            'pequeverso.com',
            'wa.me',
            'help.hotmart.com',
            'pay.hotmart.com',
            'consumer.hotmart.com',
            'refund.hotmart.com',
        }
    )
)


def build(body: bytes = BODY):
    return build_public_corpus(body, NOW, SPEC, PARSE)


def test_corpus_projects_only_published_commercial_entities_and_real_json_pointers() -> None:
    value = build()
    raw = json.loads(BODY)
    assert value.catalog_body == BODY
    assert value.revision.catalog_sha256 == hashlib.sha256(BODY).hexdigest()
    assert value.revision.parser_version == PARSER_VERSION
    assert len(value.chunks) == 2 + 9 + 26 + 6
    assert sum(e.kind is EntityKind.PRODUCT for e in value.entities) == 2
    assert sum(r.predicate is RelationKind.INCLUDES for r in value.relations) == 9
    for chunk in value.chunks:
        node = raw
        for part in chunk.source_pointer.strip('/').split('/'):
            node = node[int(part)] if isinstance(node, list) else node[part]
        assert node['id'] == chunk.source_id.split('/')[-1]
    chunks = {c.id: c for c in value.chunks}
    for relation in value.relations:
        source = chunks[relation.supporting_chunk_id]
        assert relation.subject_id.removeprefix('product:') in source.product_ids


def test_revision_is_deterministic_and_bound_to_exact_catalog_and_embedding_profile() -> None:
    value = build()
    assert build().revision == value.revision
    real_profile = build_public_corpus(
        BODY, NOW, EmbeddingSpec('openai', 'text-embedding-3-small', 1536), PARSE
    )
    assert real_profile.revision.version != value.revision.version
    modified = json.loads(BODY)
    modified['products'][0]['summary'] += ' Published correction.'
    assert build(json.dumps(modified).encode()).revision.version != value.revision.version


def test_hidden_offers_images_identity_and_questions_never_enter_the_public_projection() -> None:
    raw = json.loads(BODY)
    raw['forbidden_terms'] = ['PRIVATE_HIDDEN_OFFER_MARKER']
    raw['products'][0]['image']['alt'] = 'NON_EVIDENCE_IMAGE_MARKER'
    value = build(json.dumps(raw).encode())
    projection = repr((value.chunks, value.entities, value.relations))
    assert 'PRIVATE_HIDDEN_OFFER_MARKER' not in projection
    assert 'NON_EVIDENCE_IMAGE_MARKER' not in projection
    raw['messages'] = [{'content': 'PRIVATE_MESSAGE_MARKER'}]
    with pytest.raises(ValueError, match='Extra inputs'):
        build(json.dumps(raw).encode())


def test_affiliate_unknown_price_and_merchant_policy_remain_product_scoped() -> None:
    value = build()
    affiliate = next(c for c in value.chunks if c.id == 'product:alimentacion-bebe')
    assert json.loads(affiliate.text)['price'] is None
    assert json.loads(affiliate.text)['disclosure']
    core_policies = [c for c in value.chunks if c.kind == 'document' and 'grafismo-fonetico' in c.product_ids]
    assert core_policies
    for chunk in core_policies:
        if 'alimentacion-bebe' not in chunk.product_ids:
            assert not any(
                r.subject_id == 'product:alimentacion-bebe' and r.supporting_chunk_id == chunk.id
                for r in value.relations
            )


def test_legacy_unscoped_document_belongs_only_to_core_and_does_not_bleed_to_affiliate() -> None:
    raw = json.loads(BODY)
    raw['documents'][0]['product_ids'] = []
    value = build(json.dumps(raw).encode())
    target = f'document:{raw["documents"][0]["id"]}'
    assert {r.subject_id for r in value.relations if r.object_id == target} == {'product:grafismo-fonetico'}


def test_oversize_clause_is_rejected_without_truncating_a_policy() -> None:
    raw = json.loads(BODY)
    raw['documents'][0]['text'] = 'á' * 4001
    with pytest.raises(ValueError, match='at most 1500 characters'):
        build(json.dumps(raw).encode())


def test_unknown_host_or_unpublished_fields_are_validated_before_projection() -> None:
    raw = json.loads(BODY)
    raw['documents'][0]['url'] = 'https://attacker.invalid/policy'
    with pytest.raises(ValueError, match='host'):
        build(json.dumps(raw).encode())


def test_oversized_catalog_is_rejected_before_invoking_parser() -> None:
    def unexpected_parse(body: bytes):
        raise AssertionError('oversize input must be rejected before parse')

    with pytest.raises(ValueError, match='ingestion bound'):
        build_public_corpus(b'x' * 1_048_577, NOW, SPEC, unexpected_parse)
