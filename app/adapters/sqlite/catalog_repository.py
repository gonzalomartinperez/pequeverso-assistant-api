"""Catalog snapshots: content-addressed, activated atomically, last five kept."""

from __future__ import annotations

import sqlite3
from datetime import datetime

from app.adapters.sqlite.database import Database
from app.adapters.sqlite.stores import parse_ts, ts
from app.application.ports import StoredSnapshot
from app.domain.catalog import Catalog

KEEP_SNAPSHOTS = 5


class SqliteCatalogRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def active(self) -> StoredSnapshot | None:
        row = await self._db.read(
            lambda c: c.execute(
                'SELECT s.sha256, s.body, st.verified_at FROM catalog_state st'
                ' JOIN catalog_snapshots s ON s.sha256 = st.active_sha256 WHERE st.id = 1'
            ).fetchone()
        )
        if row is None:
            return None
        return StoredSnapshot(row['sha256'], bytes(row['body']), parse_ts(row['verified_at']))

    async def activate(self, sha256: str, body: bytes, catalog: Catalog, now: datetime) -> None:
        def work(c: sqlite3.Connection) -> None:
            c.execute(
                'INSERT OR IGNORE INTO catalog_snapshots'
                ' (sha256, schema_version, source_revision, generated_at, activated_at, body)'
                ' VALUES (?, ?, ?, ?, ?, ?)',
                (
                    sha256,
                    catalog.schema_version,
                    catalog.source_revision,
                    ts(catalog.generated_at),
                    ts(now),
                    body,
                ),
            )
            c.execute(
                'UPDATE catalog_state SET active_sha256 = ?, verified_at = ?, last_attempt_at = ?,'
                ' last_failure = NULL WHERE id = 1',
                (sha256, ts(now), ts(now)),
            )
            c.execute(
                'DELETE FROM catalog_snapshots WHERE sha256 NOT IN'
                ' (SELECT sha256 FROM catalog_snapshots ORDER BY activated_at DESC LIMIT ?)'
                ' AND sha256 != ?',
                (KEEP_SNAPSHOTS, sha256),
            )

        await self._db.write(work)

    async def mark_verified(self, sha256: str, now: datetime) -> None:
        await self._db.write(
            lambda c: c.execute(
                'UPDATE catalog_state SET verified_at = ?, last_attempt_at = ?, last_failure = NULL'
                ' WHERE id = 1 AND active_sha256 = ?',
                (ts(now), ts(now), sha256),
            )
        )

    async def record_failure(self, reason: str, now: datetime) -> None:
        await self._db.write(
            lambda c: c.execute(
                'UPDATE catalog_state SET last_attempt_at = ?, last_failure = ? WHERE id = 1',
                (ts(now), reason[:80]),
            )
        )
