"""Deterministic projection of validated public catalog fields, never visitor content."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime

from app.application.ports import CatalogParser
from app.domain.catalog import resource_key
from app.domain.knowledge import (
    MAX_PUBLIC_BODY_BYTES,
    ChunkKind,
    EmbeddingSpec,
    EntityKind,
    KnowledgeChunk,
    KnowledgeCorpus,
    KnowledgeEntity,
    KnowledgeRelation,
    KnowledgeRevision,
    RelationKind,
)

PARSER_VERSION = 'commercial-corpus-v1'


def build_public_corpus(
    body: bytes, verified_at: datetime, embedding: EmbeddingSpec, parse: CatalogParser
) -> KnowledgeCorpus:
    """Parse once, preserve exact snapshot bytes and project explicit relationships only.

    No network, embedding, visitor history, hidden offers or inferred product claims enter
    this function. Oversize clauses fail ingestion instead of silently changing their meaning.
    """
    if len(body) > MAX_PUBLIC_BODY_BYTES:
        raise ValueError('public catalog exceeds its ingestion bound')
    catalog = parse(body)
    catalog_hash = hashlib.sha256(body).hexdigest()
    identity = {
        'catalog_sha256': catalog_hash,
        'parser_version': PARSER_VERSION,
        'provider': embedding.provider,
        'model': embedding.model,
        'dimensions': embedding.dimensions,
    }
    version = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(',', ':')).encode('utf-8')
    ).hexdigest()
    revision = KnowledgeRevision(version, catalog_hash, catalog.source_revision, PARSER_VERSION, embedding)
    chunks: list[KnowledgeChunk] = []
    entities: list[KnowledgeEntity] = []
    relations: list[KnowledgeRelation] = []
    topics: dict[str, tuple[str, list[str]]] = {}

    def chunk(
        kind: ChunkKind,
        source_id: str,
        title: str,
        text: str,
        url: str,
        owners: tuple[str, ...],
        pointer: str,
    ) -> str:
        chunk_id = f'{kind.value}:{source_id}'
        chunks.append(
            KnowledgeChunk(
                chunk_id,
                kind,
                source_id,
                title,
                text,
                url,
                owners,
                hashlib.sha256(text.encode('utf-8')).hexdigest(),
                pointer,
            )
        )
        return chunk_id

    for index, product in enumerate(catalog.products):
        pointer = f'/products/{index}'
        owners: tuple[str, ...] = (product.id,)
        product_id = f'product:{product.id}'
        # Commercial numbers remain in their canonical snapshot; runtime freshness policy
        # still determines whether a retrieved price may be quoted.
        fields: dict[str, object] = {
            'name': product.name,
            'summary': product.summary,
            'kind': product.kind,
            'age_range': product.age_range,
            'format': product.format,
            'usage': product.usage,
            'pdf_count': product.pdf_count,
            'page_count': product.page_count,
            'method': product.method,
            'audience_for': product.audience_for,
            'audience_not_for': product.audience_not_for,
            'age_guidance': [{'label': a.label, 'hint': a.hint} for a in product.age_guidance],
            'disclosure': product.disclosure,
            'guarantee_days': product.guarantee_days,
            'topics': product.topics,
            'price': None
            if product.price is None
            else {
                'amount': str(product.price.amount),
                'currency': product.price.currency,
                'display': product.price.display,
                'note': product.price.note,
                'tax_note': product.price.tax_note,
            },
        }
        main = chunk(
            ChunkKind.PRODUCT,
            product.id,
            product.name,
            json.dumps(fields, ensure_ascii=False, separators=(',', ':')),
            catalog.url(product.path),
            owners,
            pointer,
        )
        entities.append(KnowledgeEntity(product_id, EntityKind.PRODUCT, product.name, (main,)))
        for resource_index, resource in enumerate(product.resources):
            rid = resource_key(product.id, resource.id)
            rp = f'{pointer}/resources/{resource_index}'
            resource_chunk = chunk(
                ChunkKind.RESOURCE,
                rid,
                resource.title,
                json.dumps(
                    {'title': resource.title, 'description': resource.description, 'pages': resource.pages},
                    ensure_ascii=False,
                    separators=(',', ':'),
                ),
                catalog.url(product.path),
                owners,
                rp,
            )
            entity_id = f'resource:{rid}'
            entities.append(
                KnowledgeEntity(entity_id, EntityKind.RESOURCE, resource.title, (resource_chunk,))
            )
            relations.append(
                KnowledgeRelation(product_id, RelationKind.INCLUDES, entity_id, resource_chunk, rp)
            )
        for topic_index, topic in enumerate(product.topics):
            # Exact published labels are shared; no synonyms, medical classification or LLM extraction.
            topic_id = 'topic:' + hashlib.sha256(topic.encode('utf-8')).hexdigest()
            if topic_id not in topics:
                topics[topic_id] = (topic, [])
            topics[topic_id][1].append(main)
            relations.append(
                KnowledgeRelation(
                    product_id,
                    RelationKind.HAS_TOPIC,
                    topic_id,
                    main,
                    f'{pointer}/topics/{topic_index}',
                )
            )

    legacy_owners = tuple(p.id for p in catalog.products if p.kind == 'core')
    for index, document in enumerate(catalog.documents):
        owners = document.product_ids or legacy_owners
        pointer = f'/documents/{index}'
        cid = chunk(
            ChunkKind.DOCUMENT,
            document.id,
            document.title,
            f'{document.title}\n{document.text}',
            document.url,
            owners,
            pointer,
        )
        eid = f'document:{document.id}'
        entities.append(KnowledgeEntity(eid, EntityKind.DOCUMENT, document.title, (cid,)))
        for owner in owners:
            relations.append(
                KnowledgeRelation(f'product:{owner}', RelationKind.HAS_DOCUMENT, eid, cid, pointer)
            )
    for index, link in enumerate(catalog.links):
        owners = link.product_ids or legacy_owners
        pointer = f'/links/{index}'
        cid = chunk(ChunkKind.LINK, link.id, link.label, link.label, link.url, owners, pointer)
        eid = f'link:{link.id}'
        entities.append(KnowledgeEntity(eid, EntityKind.LINK, link.label, (cid,)))
        for owner in owners:
            relations.append(KnowledgeRelation(f'product:{owner}', RelationKind.HAS_LINK, eid, cid, pointer))
    for topic_id, (label, support) in topics.items():
        entities.append(KnowledgeEntity(topic_id, EntityKind.TOPIC, label, tuple(dict.fromkeys(support))))
    return KnowledgeCorpus(revision, body, verified_at, tuple(chunks), tuple(entities), tuple(relations))
