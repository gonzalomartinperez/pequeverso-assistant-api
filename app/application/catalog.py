"""Keeps one valid catalog snapshot active. A failed or invalid fetch is recorded and never
replaces the snapshot in force; an unchanged document only refreshes its verification time.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import timedelta

from app.application.ports import CatalogParser, CatalogRepository, CatalogSource, Clock
from app.domain.catalog import ActiveCatalog

log = logging.getLogger(__name__)


class CatalogService:
    def __init__(
        self,
        source: CatalogSource,
        parse: CatalogParser,
        repository: CatalogRepository,
        clock: Clock,
        max_price_age: timedelta,
    ) -> None:
        self._source = source
        self._parse = parse
        self._repository = repository
        self._clock = clock
        self._max_price_age = max_price_age
        self._active: ActiveCatalog | None = None

    @property
    def active(self) -> ActiveCatalog | None:
        return self._active

    async def load(self) -> None:
        """Restore the last activated snapshot (e.g. after a restart) without fetching."""
        stored = await self._repository.active()
        if stored is None:
            return
        try:
            catalog = self._parse(stored.body)
        except ValueError:
            log.warning('{"operation":"catalog_restore","outcome":"invalid_stored_snapshot"}')
            return
        self._active = ActiveCatalog(catalog, stored.sha256, stored.verified_at, self._max_price_age)

    async def refresh(self) -> bool:
        """Fetch, validate and activate. Returns True when a valid catalog is in force afterwards."""
        now = self._clock.now()
        try:
            body = await self._source.fetch()
            catalog = self._parse(body)
        except Exception as error:  # noqa: BLE001 - every failure keeps the active snapshot
            reason = type(error).__name__
            await self._repository.record_failure(reason, now)
            log.warning('{"operation":"catalog_refresh","outcome":"failed","reason":"%s"}', reason)
            return self._active is not None
        sha = hashlib.sha256(body).hexdigest()
        verified_at = now if self._source.live else min(now, catalog.generated_at)
        if self._active is not None and self._active.sha256 == sha:
            await self._repository.mark_verified(sha, verified_at)
        else:
            await self._repository.activate(sha, body, catalog, verified_at)
            log.info('{"operation":"catalog_refresh","outcome":"activated","sha256":"%s"}', sha[:12])
        self._active = ActiveCatalog(catalog, sha, verified_at, self._max_price_age)
        return True
