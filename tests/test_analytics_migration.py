"""Offline migration state transitions; SQL execution/persistence still requires isolated PG."""

import asyncio
import hashlib
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from app.adapters.postgres.database import PostgresDatabase


class MigrationConnection:
    def __init__(self, markers):
        self.markers = markers
        self.current = None
        self.executed = []
        self.row = None

    async def execute(self, query, params=None):
        text = query if isinstance(query, str) else query.as_string()
        self.executed.append(text)
        if text == 'SELECT to_regclass(%s) AS relation':
            self.current = params[0].split('.')[-1]
            self.row = {'relation': self.current if self.current in self.markers else None}
        elif text.startswith('SELECT checksum FROM'):
            self.row = {'checksum': self.markers[self.current]}
        elif text.startswith('INSERT INTO "assistant_private".'):
            marker = text.split('"')[3]
            self.markers.setdefault(marker, params[1])
        else:
            self.row = None
        return self

    async def fetchone(self):
        return self.row


class MigrationPool:
    def __init__(self, connection):
        self.value = connection

    @asynccontextmanager
    async def connection(self):
        yield self.value


def migrate(connection):
    # Exercise the real method without constructing a pool, opening sockets or changing SQL.
    database = object.__new__(PostgresDatabase)
    database.pool = MigrationPool(connection)
    asyncio.run(database.migrate())


def test_migration_backfill_is_once_only_and_both_checksum_markers_remain_mandatory():
    connection = MigrationConnection({})
    migrate(connection)
    source = Path('app/adapters/postgres/006_analytics_classification_country.sql').read_text()
    assert connection.executed.count(source) == 1
    assert set(connection.markers) == {'analytics_schema', 'analytics_schema_v2'}
    assert connection.markers['analytics_schema_v2'] == hashlib.sha256(source.encode()).hexdigest()
    migrate(connection)
    assert connection.executed.count(source) == 1  # Deleted/expired v2 rows cannot be backfilled again.
    for marker in ('analytics_schema', 'analytics_schema_v2'):
        invalid = MigrationConnection({**connection.markers, marker: 'a' * 64})
        with pytest.raises(RuntimeError, match='checksum mismatch'):
            migrate(invalid)
        assert source not in invalid.executed


def test_persisted_country_allowlist_matches_boundary_and_report_schema_exactly():
    import re

    from app.domain.analytics_country import COUNTRIES
    from app.presentation.product_analytics import Country

    migration = Path('app/adapters/postgres/006_analytics_classification_country.sql').read_text()
    constraint = migration.split('country text NOT NULL CHECK(country IN (', 1)[1].split('))', 1)[0]
    assert set(re.findall(r"'([^']+)'", constraint)) == COUNTRIES | {'unknown'}
    assert set(Country.model_json_schema()['properties']['code']['enum']) == COUNTRIES | {
        'unknown',
        'withheld',
    }
