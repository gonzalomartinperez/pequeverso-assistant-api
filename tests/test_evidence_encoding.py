"""Model evidence retains complete canonical facts through its compact internal encoding."""

import json

import pytest

from app.adapters.catalog_schema import CatalogParser
from app.ai.evidence import catalog_payload, decode_documents
from app.domain.catalog import PriceStatus
from tests.support import CATALOG_BYTES


def test_document_table_roundtrips_every_canonical_document_and_scope() -> None:
    catalog = CatalogParser(frozenset({'pequeverso.com', 'consumer.hotmart.com', 'refund.hotmart.com'}))(
        CATALOG_BYTES
    )
    store = json.loads(catalog_payload(catalog, PriceStatus.VERIFIED, '', 40000))
    documents = decode_documents(store['documents'])
    assert documents == [
        {
            'id': d.id,
            'kind': d.kind.value,
            'title': d.title,
            'text': d.text,
            'product_ids': list(d.product_ids),
        }
        for d in catalog.documents
    ]
    by_id = {d['id']: d for d in documents}
    limits = by_id['support.limits']
    assert limits['title'] == 'Lo que no podemos hacer'
    assert limits['text'].startswith('Ver o modificar datos de pago.')
    assert by_id['support.access.2']['title'] == 'Pagué con boleto, transferencia o efectivo'
    assert {p['id'] for p in store['products']} == {p.id for p in catalog.products}
    core, affiliate = store['products']
    assert catalog.products[0].price is not None
    assert core['price']['display'] == catalog.products[0].price.display
    assert len(core['resources']) == 9 and core['page_count'] == 414
    assert affiliate['price'] is None


@pytest.mark.parametrize(
    'table',
    [
        {'columns': ['text', 'id', 'kind', 'title', 'product_ids'], 'rows': []},
        {'columns': ['id', 'kind', 'title', 'text', 'product_ids'], 'rows': [['incomplete']]},
        {'columns': ['id', 'kind', 'title', 'text', 'product_ids'], 'rows': None},
    ],
)
def test_document_decoder_refuses_reordered_columns_or_incomplete_rows(table: dict[str, object]) -> None:
    with pytest.raises(ValueError, match='invalid document'):
        decode_documents(table)
