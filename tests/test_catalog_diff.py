"""Semantic catalog diff: retired products, price and document changes are reported."""

from __future__ import annotations

import json
from typing import Any

from app.adapters.catalog_schema import CatalogParser
from app.application.catalog_diff import diff
from app.bootstrap.config import Settings
from tests.support import CATALOG_BYTES

PARSE = CatalogParser(frozenset(Settings.model_fields['catalog_allowed_hosts'].default))


def _variant(change: Any) -> bytes:
    data = json.loads(CATALOG_BYTES)
    change(data)
    return json.dumps(data).encode()


def test_identical_snapshots_have_no_fact_changes() -> None:
    assert diff(PARSE(CATALOG_BYTES), PARSE(CATALOG_BYTES)).empty


def test_price_document_and_retirement_changes_are_reported() -> None:
    before = PARSE(CATALOG_BYTES)

    def change(data: dict[str, Any]) -> None:
        data['products'][0]['price']['amount'] = '19.99'
        data['documents'][0]['text'] += ' Actualizado.'
        data['documents'].pop()

    after = PARSE(_variant(change))
    result = diff(before, after)
    assert result.price_changes == {'grafismo-fonetico': ('14.99 USD', '19.99 USD')}
    assert result.documents_changed == [before.documents[0].id]
    assert result.documents_removed == [before.documents[-1].id]
    assert not result.empty


def test_first_sync_reports_everything_as_added() -> None:
    result = diff(None, PARSE(CATALOG_BYTES))
    assert result.products_added == ['grafismo-fonetico'] and not result.products_retired
