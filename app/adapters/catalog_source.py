"""Where the catalog document comes from: one fixed https URL, or a local file (fixture mode).

The URL is configuration, never request input. Redirects are refused, the host must be
allowlisted, and the body is read with a hard size cap, so ingestion cannot be steered to
internal addresses or exhaust memory.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit

import httpx

from app.adapters.catalog_schema import MAX_CATALOG_BYTES


class FileCatalogSource:
    live = False

    def __init__(self, path: Path) -> None:
        self._path = path

    async def fetch(self) -> bytes:
        data = self._path.read_bytes()
        if len(data) > MAX_CATALOG_BYTES:
            raise ValueError('catalog too large')
        return data


class HttpCatalogSource:
    live = True

    def __init__(
        self,
        url: str,
        allowed_hosts: frozenset[str],
        timeout_seconds: float = 5.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        parts = urlsplit(url)
        if parts.scheme != 'https' or parts.hostname not in allowed_hosts or parts.username or parts.password:
            raise ValueError('catalog URL must be https on an allowed host')
        self._url = url
        self._timeout = httpx.Timeout(timeout_seconds)
        self._transport = transport

    async def fetch(self) -> bytes:
        async with (
            httpx.AsyncClient(
                timeout=self._timeout, follow_redirects=False, trust_env=False, transport=self._transport
            ) as client,
            client.stream('GET', self._url, headers={'Accept': 'application/json'}) as response,
        ):
            if response.status_code != 200:
                raise ConnectionError(f'catalog fetch returned {response.status_code}')
            content_type = response.headers.get('content-type', '')
            if not content_type.startswith('application/json'):
                raise ValueError('catalog must be served as application/json')
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > MAX_CATALOG_BYTES:
                    raise ValueError('catalog too large')
            return bytes(body)
