import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.adapters.catalog_schema import CatalogParser
from app.adapters.catalog_source import FileCatalogSource, HttpCatalogSource
from app.adapters.sqlite.catalog_repository import SqliteCatalogRepository
from app.adapters.sqlite.database import Database
from app.application.catalog import CatalogService
from app.domain.answer_policy import fold
from app.domain.catalog import PriceStatus
from tests.support import CATALOG_BYTES, FixedClock

HOSTS = frozenset({'pequeverso.com', 'consumer.hotmart.com', 'refund.hotmart.com'})
PARSE = CatalogParser(HOSTS)


def _mutated(**changes: Any) -> bytes:
    data = json.loads(CATALOG_BYTES)
    for path, value in changes.items():
        target = data
        keys = path.split('__')
        for key in keys[:-1]:
            target = target[int(key)] if key.isdigit() else target[key]
        target[keys[-1]] = value
    return json.dumps(data).encode()


def test_committed_snapshot_is_valid_and_grounded() -> None:
    catalog = PARSE(CATALOG_BYTES)
    product = catalog.product('grafismo-fonetico')
    assert product is not None
    assert product.pdf_count == len(product.resources) == 9
    assert sum(r.pages or 0 for r in product.resources) == product.page_count == 414
    assert str(product.price.amount) == '14.99'
    assert len(catalog.source_revision) == 40
    assert catalog.link(catalog.site.support_link_id) is not None


def test_snapshot_never_exposes_post_purchase_offer() -> None:
    catalog = PARSE(CATALOG_BYTES)
    assert catalog.forbidden_terms, 'offer names must be forbidden answer terms'
    data = json.loads(CATALOG_BYTES)
    data.pop('forbidden_terms')
    text = fold(json.dumps(data, ensure_ascii=False))
    for term in catalog.forbidden_terms:
        assert fold(term) not in text


@pytest.mark.parametrize(
    'body',
    [
        _mutated(links__0__url='http://pequeverso.com/soporte/'),
        _mutated(links__0__url='https://evil.example/soporte/'),
        _mutated(links__0__url='https://user:pw@pequeverso.com/'),
        _mutated(site__origin='https://pequeverso.com/sub'),
        _mutated(products__0__price__amount='-1'),
        _mutated(products__0__unexpected='x'),
        _mutated(site__support_link_id='missing'),
        _mutated(generated_at='2026-09-27T17:00:00'),
        _mutated(products__0__image__url='https://169.254.169.254/latest'),
        b'{"not": "a catalog"}',
        b'x' * (300 * 1024),
    ],
)
def test_parser_rejects_unsafe_or_malformed_catalogs(body: bytes) -> None:
    with pytest.raises(ValueError):  # noqa: PT011 - pydantic and custom errors both subclass ValueError
        PARSE(body)


class _Source:
    def __init__(self, bodies: list[bytes | Exception], live: bool = True) -> None:
        self.bodies = bodies
        self.live = live

    async def fetch(self) -> bytes:
        item = self.bodies.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _service(tmp_path: Path, source: Any, clock: FixedClock) -> tuple[CatalogService, Database]:
    db = Database(str(tmp_path / 'c.sqlite3'))
    return CatalogService(source, PARSE, SqliteCatalogRepository(db), clock, timedelta(hours=168)), db


def test_failed_refresh_keeps_active_snapshot_and_restart_restores_it(tmp_path: Path) -> None:
    async def scenario() -> None:
        clock = FixedClock()
        changed = _mutated(products__0__summary='Resumen nuevo del kit.')
        service, db = _service(tmp_path, _Source([CATALOG_BYTES, ConnectionError(), b'{bad', changed]), clock)
        await db.open()
        assert await service.refresh()
        first = service.active
        assert first is not None
        assert await service.refresh()  # fetch error: still serving
        assert await service.refresh()  # invalid document: still serving
        assert service.active is first
        clock.advance(hours=1)
        assert await service.refresh()
        assert service.active is not None and service.active.sha256 != first.sha256
        await db.close()

        restarted, db2 = _service(tmp_path, _Source([]), clock)
        await db2.open()
        await restarted.load()
        assert restarted.active is not None
        assert restarted.active.catalog.products[0].summary == 'Resumen nuevo del kit.'
        await db2.close()

    asyncio.run(scenario())


def test_unchanged_live_document_only_refreshes_verification(tmp_path: Path) -> None:
    async def scenario() -> None:
        clock = FixedClock()
        service, db = _service(tmp_path, _Source([CATALOG_BYTES, CATALOG_BYTES]), clock)
        await db.open()
        await service.refresh()
        clock.advance(days=10)
        await service.refresh()
        assert service.active is not None
        assert service.active.price_status(clock.now()) is PriceStatus.VERIFIED
        await db.close()

    asyncio.run(scenario())


def test_bundled_snapshot_prices_age_from_export_time(tmp_path: Path) -> None:
    async def scenario() -> None:
        generated = PARSE(CATALOG_BYTES).generated_at
        clock = FixedClock(generated + timedelta(days=30))
        path = tmp_path / 'catalog.json'
        path.write_bytes(CATALOG_BYTES)
        service, db = _service(tmp_path, FileCatalogSource(path), clock)
        await db.open()
        await service.refresh()
        assert service.active is not None
        assert service.active.verified_at == generated
        assert service.active.price_status(clock.now()) is PriceStatus.UNVERIFIED
        await db.close()

    asyncio.run(scenario())


def test_http_source_refuses_redirects_wrong_types_and_oversize() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == '/redirect.json':
            return httpx.Response(302, headers={'location': 'http://169.254.169.254/'})
        if request.url.path == '/html.json':
            return httpx.Response(200, text='<html>', headers={'content-type': 'text/html'})
        if request.url.path == '/huge.json':
            return httpx.Response(
                200, content=b'x' * (300 * 1024), headers={'content-type': 'application/json'}
            )
        return httpx.Response(200, content=CATALOG_BYTES, headers={'content-type': 'application/json'})

    transport = httpx.MockTransport(handler)

    async def fetch(path: str) -> bytes:
        return await HttpCatalogSource(f'https://pequeverso.com{path}', HOSTS, transport=transport).fetch()

    assert asyncio.run(fetch('/assistant/catalog.v1.json')) == CATALOG_BYTES
    for path, error in (
        ('/redirect.json', ConnectionError),
        ('/html.json', ValueError),
        ('/huge.json', ValueError),
    ):
        with pytest.raises(error):
            asyncio.run(fetch(path))
    for url in ('http://pequeverso.com/c.json', 'https://127.0.0.1/c.json', 'https://evil.example/c.json'):
        with pytest.raises(ValueError, match='allowed host'):
            HttpCatalogSource(url, HOSTS)


def test_generated_at_is_timezone_aware() -> None:
    assert PARSE(CATALOG_BYTES).generated_at.tzinfo is not None
    assert PARSE(CATALOG_BYTES).generated_at <= datetime.now(UTC)
