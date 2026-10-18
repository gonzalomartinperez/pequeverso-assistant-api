"""Owned bounded Neo4j driver; only bootstrap/job composition wires its lifecycle."""

from __future__ import annotations

from urllib.parse import urlsplit

from neo4j import AsyncGraphDatabase


class Neo4jDatabase:
    def __init__(self, uri: str, username: str, password: str) -> None:
        location = urlsplit(uri)
        if (
            location.scheme not in {'bolt', 'bolt+s', 'neo4j', 'neo4j+s'}
            or not location.hostname
            or location.username
            or location.password
            or location.query
            or location.fragment
            or not username
            or not password
        ):
            raise ValueError('graph connection requires explicit private credentials and a valid URI')
        self.driver = AsyncGraphDatabase.driver(
            uri,
            auth=(username, password),
            max_connection_pool_size=4,
            connection_timeout=3.0,
            connection_acquisition_timeout=3.0,
            max_transaction_retry_time=0.0,
            disable_auto_commit_retries=True,
            telemetry_disabled=True,
            max_connection_lifetime=300.0,
        )
        self._closed = False
        self._opened = False

    async def open(self) -> None:
        if self._closed:
            raise RuntimeError('graph database is already closed')
        if self._opened:
            return
        try:
            await self.driver.verify_connectivity()
        except BaseException:
            await self.close()
            raise
        self._opened = True

    async def close(self) -> None:
        if not self._closed:
            self._closed = True
            await self.driver.close()
